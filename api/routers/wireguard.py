"""WireGuard router -- /api/v1/wireguard (admin only)."""

from __future__ import annotations

import base64
import io
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import require_role
from api.models.activity_log import ActivityLog
from api.models.users import User

logger = logging.getLogger("novapanel.wireguard")

router = APIRouter()

_admin = require_role("admin")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(db: AsyncSession, request: Request, user_id, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(
        user_id=user_id,
        action=action,
        details=details,
        ip_address=client_ip,
    ))


def _generate_qr_base64(text: str) -> str:
    """Generate a QR code PNG as a base64-encoded string."""
    try:
        import qrcode
        qr = qrcode.make(text)
        buf = io.BytesIO()
        qr.save(buf, format="PNG")
        buf.seek(0)
        return base64.b64encode(buf.read()).decode()
    except ImportError:
        logger.warning("qrcode library not installed; QR generation unavailable")
        return ""


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PeerCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    allowed_ips: str = Field(default="0.0.0.0/0, ::/0", max_length=512)
    dns: str = Field(default="1.1.1.1", max_length=256)


class PeerResponse(BaseModel):
    id: str
    name: str
    public_key: str
    allowed_ips: str
    endpoint: str | None = None
    latest_handshake: str | None = None
    transfer_rx: int = 0
    transfer_tx: int = 0


class PeerCreateResponse(BaseModel):
    peer: PeerResponse
    client_config: str
    qr_code_base64: str


class WireGuardStatusResponse(BaseModel):
    interface: str
    public_key: str
    listening_port: int
    peer_count: int


# ---------------------------------------------------------------------------
# GET /peers -- list all WireGuard peers
# ---------------------------------------------------------------------------
@router.get("/peers", status_code=status.HTTP_200_OK)
async def list_peers(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
) -> list[PeerResponse]:
    agent = request.app.state.agent
    try:
        result = await agent._request("GET", "/wireguard/peers")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch WireGuard peers: {exc}",
        )

    peers = result.get("peers", [])
    return [
        PeerResponse(
            id=p.get("id", ""),
            name=p.get("name", ""),
            public_key=p.get("public_key", ""),
            allowed_ips=p.get("allowed_ips", ""),
            endpoint=p.get("endpoint"),
            latest_handshake=p.get("latest_handshake"),
            transfer_rx=p.get("transfer_rx", 0),
            transfer_tx=p.get("transfer_tx", 0),
        )
        for p in peers
    ]


# ---------------------------------------------------------------------------
# POST /peers -- create new peer, return config + QR code
# ---------------------------------------------------------------------------
@router.post("/peers", response_model=PeerCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_peer(
    body: PeerCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    agent = request.app.state.agent
    try:
        result = await agent._request("POST", "/wireguard/peers", json_body={
            "name": body.name,
            "allowed_ips": body.allowed_ips,
            "dns": body.dns,
        })
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to create WireGuard peer: {exc}",
        )

    peer_data = result.get("peer", {})
    client_config = result.get("client_config", "")

    qr_b64 = _generate_qr_base64(client_config) if client_config else ""

    _log(db, request, admin.id, "wireguard.peer.create", f"Created peer '{body.name}'")

    return PeerCreateResponse(
        peer=PeerResponse(
            id=peer_data.get("id", ""),
            name=peer_data.get("name", body.name),
            public_key=peer_data.get("public_key", ""),
            allowed_ips=peer_data.get("allowed_ips", body.allowed_ips),
            endpoint=peer_data.get("endpoint"),
        ),
        client_config=client_config,
        qr_code_base64=qr_b64,
    )


# ---------------------------------------------------------------------------
# DELETE /peers/{id} -- remove peer
# ---------------------------------------------------------------------------
@router.delete("/peers/{peer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_peer(
    peer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    agent = request.app.state.agent
    try:
        await agent._request("DELETE", f"/wireguard/peers/{peer_id}")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to delete WireGuard peer: {exc}",
        )

    _log(db, request, admin.id, "wireguard.peer.delete", f"Deleted peer {peer_id}")


# ---------------------------------------------------------------------------
# GET /peers/{id}/config -- download client config file
# ---------------------------------------------------------------------------
@router.get("/peers/{peer_id}/config", status_code=status.HTTP_200_OK)
async def get_peer_config(
    peer_id: str,
    request: Request,
    admin: User = Depends(_admin),
):
    agent = request.app.state.agent
    try:
        result = await agent._request("GET", f"/wireguard/peers/{peer_id}/config")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch peer config: {exc}",
        )

    config_text = result.get("config", "")
    return PlainTextResponse(
        content=config_text,
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename=wg-peer-{peer_id}.conf"},
    )


# ---------------------------------------------------------------------------
# GET /peers/{id}/qr -- return QR code image
# ---------------------------------------------------------------------------
@router.get("/peers/{peer_id}/qr", status_code=status.HTTP_200_OK)
async def get_peer_qr(
    peer_id: str,
    request: Request,
    admin: User = Depends(_admin),
):
    agent = request.app.state.agent
    try:
        result = await agent._request("GET", f"/wireguard/peers/{peer_id}/config")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch peer config: {exc}",
        )

    config_text = result.get("config", "")
    if not config_text:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Peer config not found.")

    try:
        import qrcode
        qr = qrcode.make(config_text)
        buf = io.BytesIO()
        qr.save(buf, format="PNG")
        buf.seek(0)
        return Response(content=buf.read(), media_type="image/png")
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="QR code generation not available (qrcode library missing).",
        )


# ---------------------------------------------------------------------------
# GET /status -- WireGuard interface status
# ---------------------------------------------------------------------------
@router.get("/status", response_model=WireGuardStatusResponse, status_code=status.HTTP_200_OK)
async def wireguard_status(
    request: Request,
    admin: User = Depends(_admin),
):
    agent = request.app.state.agent
    try:
        result = await agent._request("GET", "/wireguard/status")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch WireGuard status: {exc}",
        )

    return WireGuardStatusResponse(
        interface=result.get("interface", "wg0"),
        public_key=result.get("public_key", ""),
        listening_port=result.get("listening_port", 0),
        peer_count=result.get("peer_count", 0),
    )
