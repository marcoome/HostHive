"""WireGuard router -- /api/v1/wireguard (admin only).

Uses WireguardService directly instead of proxying through agent.
"""

from __future__ import annotations

import asyncio
import io
import logging
from functools import partial
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.database import get_db
from api.core.security import require_role
from api.models.activity_log import ActivityLog
from api.models.users import User
from api.services.wireguard_service import WireguardService

logger = logging.getLogger("hosthive.wireguard")

router = APIRouter()
_admin = require_role("admin")


def _get_wg_service() -> WireguardService:
    endpoint = getattr(settings, "server_ip", "127.0.0.1")
    return WireguardService(endpoint=endpoint)


def _log(db: AsyncSession, request: Request, user_id, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PeerCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    allowed_ips: str = Field(default="0.0.0.0/0, ::/0", max_length=512)
    dns: str = Field(default="1.1.1.1", max_length=256)


class PeerResponse(BaseModel):
    id: str = ""
    name: str = ""
    public_key: str = ""
    allowed_ips: str = ""
    endpoint: str | None = None
    latest_handshake: str | None = None
    transfer_rx: int = 0
    transfer_tx: int = 0


class PeerCreateResponse(BaseModel):
    peer: PeerResponse
    client_config: str
    qr_code_base64: str


class WireGuardStatusResponse(BaseModel):
    interface: str = "wg0"
    public_key: str = ""
    listening_port: int = 0
    peer_count: int = 0


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------
@router.get("/status", response_model=WireGuardStatusResponse)
async def wireguard_status(admin: User = Depends(_admin)):
    wg = _get_wg_service()
    loop = asyncio.get_running_loop()
    try:
        peers = await loop.run_in_executor(None, wg.list_peers)
        pub_key = await loop.run_in_executor(None, wg._get_server_public_key)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"WireGuard not available: {exc}")

    return WireGuardStatusResponse(
        interface="wg0",
        public_key=pub_key,
        listening_port=wg._listen_port,
        peer_count=len(peers),
    )


# ---------------------------------------------------------------------------
# GET /peers
# ---------------------------------------------------------------------------
@router.get("/peers")
async def list_peers(admin: User = Depends(_admin)):
    wg = _get_wg_service()
    loop = asyncio.get_running_loop()
    try:
        peers = await loop.run_in_executor(None, wg.list_peers)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list peers: {exc}")

    return [
        PeerResponse(
            id=p.get("public_key", "")[:8],
            name=p.get("name", p.get("public_key", "")[:8]),
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
# POST /peers
# ---------------------------------------------------------------------------
@router.post("/peers", response_model=PeerCreateResponse, status_code=201)
async def create_peer(
    body: PeerCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    wg = _get_wg_service()
    loop = asyncio.get_running_loop()
    try:
        peer = await loop.run_in_executor(
            None, partial(wg.create_peer, body.name, body.allowed_ips)
        )
        config = wg.generate_client_config(peer)
        qr_b64 = await loop.run_in_executor(None, partial(WireguardService.generate_qr_code, config))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create peer: {exc}")

    _log(db, request, admin.id, "wireguard.peer.create", f"Created peer '{body.name}'")

    return PeerCreateResponse(
        peer=PeerResponse(
            id=peer.public_key[:8],
            name=peer.name,
            public_key=peer.public_key,
            allowed_ips=peer.allowed_ips,
        ),
        client_config=config,
        qr_code_base64=qr_b64,
    )


# ---------------------------------------------------------------------------
# DELETE /peers/{peer_id}
# ---------------------------------------------------------------------------
@router.delete("/peers/{peer_id}", status_code=204)
async def delete_peer(
    peer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin),
):
    wg = _get_wg_service()
    loop = asyncio.get_running_loop()

    # peer_id is first 8 chars of public key - find full key
    peers = await loop.run_in_executor(None, wg.list_peers)
    full_key = None
    for p in peers:
        pk = p.get("public_key", "")
        if pk.startswith(peer_id) or pk[:8] == peer_id:
            full_key = pk
            break

    if not full_key:
        raise HTTPException(status_code=404, detail="Peer not found")

    try:
        await loop.run_in_executor(None, partial(wg.delete_peer, full_key))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete peer: {exc}")

    _log(db, request, admin.id, "wireguard.peer.delete", f"Deleted peer {peer_id}")


# ---------------------------------------------------------------------------
# GET /peers/{peer_id}/config
# ---------------------------------------------------------------------------
@router.get("/peers/{peer_id}/config")
async def get_peer_config(peer_id: str, admin: User = Depends(_admin)):
    wg = _get_wg_service()
    loop = asyncio.get_running_loop()
    peers = await loop.run_in_executor(None, wg.list_peers)

    for p in peers:
        pk = p.get("public_key", "")
        if pk.startswith(peer_id) or pk[:8] == peer_id:
            # Rebuild a minimal config from peer data
            config = f"[Peer]\nPublicKey = {pk}\nAllowedIPs = {p.get('allowed_ips', '')}\nEndpoint = {wg._endpoint}:{wg._listen_port}\n"
            return PlainTextResponse(content=config, headers={
                "Content-Disposition": f"attachment; filename=wg-peer-{peer_id}.conf"
            })

    raise HTTPException(status_code=404, detail="Peer not found")


# ---------------------------------------------------------------------------
# GET /peers/{peer_id}/qr
# ---------------------------------------------------------------------------
@router.get("/peers/{peer_id}/qr")
async def get_peer_qr(peer_id: str, admin: User = Depends(_admin)):
    wg = _get_wg_service()
    loop = asyncio.get_running_loop()
    peers = await loop.run_in_executor(None, wg.list_peers)

    for p in peers:
        pk = p.get("public_key", "")
        if pk.startswith(peer_id) or pk[:8] == peer_id:
            config = f"[Peer]\nPublicKey = {pk}\nAllowedIPs = {p.get('allowed_ips', '')}\nEndpoint = {wg._endpoint}:{wg._listen_port}\n"
            try:
                import qrcode
                qr = qrcode.make(config)
                buf = io.BytesIO()
                qr.save(buf, format="PNG")
                buf.seek(0)
                return Response(content=buf.read(), media_type="image/png")
            except ImportError:
                raise HTTPException(status_code=501, detail="qrcode library not installed")

    raise HTTPException(status_code=404, detail="Peer not found")
