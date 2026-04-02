"""HostHive MCP Server — Model Context Protocol endpoint.

A FastAPI application that implements the MCP JSON-RPC protocol on port 8765.
Authenticated via Bearer token.  Only starts when MCP is enabled in config.

Supports:
    - initialize
    - tools/list
    - tools/call
    - resources/list
    - resources/read
"""

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.mcp.auth import verify_mcp_bearer
from api.mcp.tools import call_tool, list_tools

log = logging.getLogger("novapanel.mcp")

# ---------------------------------------------------------------------------
# MCP protocol constants
# ---------------------------------------------------------------------------

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "hosthive"
SERVER_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

mcp_app = FastAPI(
    title="HostHive MCP Server",
    description="Model Context Protocol server for HostHive hosting panel",
    docs_url=None,
    redoc_url=None,
)

mcp_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# JSON-RPC request / response models
# ---------------------------------------------------------------------------

class JSONRPCRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[int | str] = None
    method: str
    params: Optional[Dict[str, Any]] = None


class JSONRPCError(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None


class JSONRPCResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[int | str] = None
    result: Optional[Any] = None
    error: Optional[JSONRPCError] = None


# ---------------------------------------------------------------------------
# MCP resource definitions
# ---------------------------------------------------------------------------

_RESOURCES = [
    {
        "uri": "hosthive://server/stats",
        "name": "Server Statistics",
        "description": "Real-time CPU, memory, disk, and network statistics.",
        "mimeType": "application/json",
    },
    {
        "uri": "hosthive://server/services",
        "name": "Service Status",
        "description": "Status of all monitored system services.",
        "mimeType": "application/json",
    },
    {
        "uri": "hosthive://domains/list",
        "name": "Domain List",
        "description": "All configured domains and virtual hosts.",
        "mimeType": "application/json",
    },
]


async def _read_resource(uri: str) -> Any:
    """Read a resource by URI, delegating to agent calls."""
    from api.core.agent_client import AgentClient

    agent = AgentClient()
    try:
        if uri == "hosthive://server/stats":
            return await agent.get_server_stats()
        elif uri == "hosthive://server/services":
            return await agent._request("GET", "/system/services")
        elif uri == "hosthive://domains/list":
            return await agent._request("GET", "/nginx/vhosts")
        else:
            raise ValueError(f"Unknown resource URI: {uri!r}")
    finally:
        await agent.close()


# ---------------------------------------------------------------------------
# Audit logging helper
# ---------------------------------------------------------------------------

def _audit(method: str, params: Any, result: Any = None, error: str | None = None) -> None:
    """Log MCP operations for audit trail."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "mcp_method": method,
        "params": params,
    }
    if error:
        entry["error"] = error
        log.warning("MCP audit: %s", json.dumps(entry, default=str))
    else:
        log.info("MCP audit: %s", json.dumps(entry, default=str))


# ---------------------------------------------------------------------------
# MCP method handlers
# ---------------------------------------------------------------------------

async def _handle_initialize(params: dict[str, Any] | None) -> dict[str, Any]:
    """Handle the ``initialize`` MCP method."""
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {
            "tools": {"listChanged": False},
            "resources": {"subscribe": False, "listChanged": False},
        },
        "serverInfo": {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
        },
    }


async def _handle_tools_list(params: dict[str, Any] | None) -> dict[str, Any]:
    """Handle ``tools/list``."""
    return {"tools": list_tools()}


async def _handle_tools_call(params: dict[str, Any] | None) -> dict[str, Any]:
    """Handle ``tools/call``."""
    if not params or "name" not in params:
        raise ValueError("tools/call requires 'name' in params")

    tool_name = params["name"]
    arguments = params.get("arguments", {})

    try:
        result = await call_tool(tool_name, arguments)
        _audit("tools/call", {"tool": tool_name, "arguments": arguments})
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, default=str) if not isinstance(result, str) else result,
                }
            ],
            "isError": False,
        }
    except Exception as exc:
        _audit("tools/call", {"tool": tool_name, "arguments": arguments}, error=str(exc))
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Error: {exc}",
                }
            ],
            "isError": True,
        }


async def _handle_resources_list(params: dict[str, Any] | None) -> dict[str, Any]:
    """Handle ``resources/list``."""
    return {"resources": _RESOURCES}


async def _handle_resources_read(params: dict[str, Any] | None) -> dict[str, Any]:
    """Handle ``resources/read``."""
    if not params or "uri" not in params:
        raise ValueError("resources/read requires 'uri' in params")

    uri = params["uri"]
    try:
        data = await _read_resource(uri)
        _audit("resources/read", {"uri": uri})
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(data, default=str),
                }
            ],
        }
    except Exception as exc:
        _audit("resources/read", {"uri": uri}, error=str(exc))
        raise


# Method dispatch table
_HANDLERS: Dict[str, Any] = {
    "initialize": _handle_initialize,
    "tools/list": _handle_tools_list,
    "tools/call": _handle_tools_call,
    "resources/list": _handle_resources_list,
    "resources/read": _handle_resources_read,
}


# ---------------------------------------------------------------------------
# Main MCP endpoint
# ---------------------------------------------------------------------------

@mcp_app.post("/mcp")
async def mcp_endpoint(
    request: Request,
    _token: str = Depends(verify_mcp_bearer),
) -> JSONResponse:
    """Main MCP JSON-RPC endpoint.

    Accepts a single JSON-RPC request and dispatches to the appropriate handler.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            content=JSONRPCResponse(
                error=JSONRPCError(code=-32700, message="Parse error"),
            ).model_dump(exclude_none=True),
            status_code=200,
        )

    try:
        rpc = JSONRPCRequest(**body)
    except Exception as exc:
        return JSONResponse(
            content=JSONRPCResponse(
                error=JSONRPCError(code=-32600, message=f"Invalid request: {exc}"),
            ).model_dump(exclude_none=True),
            status_code=200,
        )

    handler = _HANDLERS.get(rpc.method)
    if handler is None:
        # Notifications (no id) for unknown methods are silently ignored per spec
        if rpc.id is None:
            return JSONResponse(content={}, status_code=204)
        return JSONResponse(
            content=JSONRPCResponse(
                id=rpc.id,
                error=JSONRPCError(code=-32601, message=f"Method not found: {rpc.method}"),
            ).model_dump(exclude_none=True),
            status_code=200,
        )

    try:
        result = await handler(rpc.params)
        return JSONResponse(
            content=JSONRPCResponse(
                id=rpc.id,
                result=result,
            ).model_dump(exclude_none=True),
            status_code=200,
        )
    except ValueError as exc:
        return JSONResponse(
            content=JSONRPCResponse(
                id=rpc.id,
                error=JSONRPCError(code=-32602, message=str(exc)),
            ).model_dump(exclude_none=True),
            status_code=200,
        )
    except Exception as exc:
        log.error("MCP handler error: %s", exc, exc_info=True)
        return JSONResponse(
            content=JSONRPCResponse(
                id=rpc.id,
                error=JSONRPCError(code=-32603, message=f"Internal error: {exc}"),
            ).model_dump(exclude_none=True),
            status_code=200,
        )


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

@mcp_app.get("/health")
async def health():
    return {"status": "ok", "server": SERVER_NAME, "version": SERVER_VERSION}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

MCP_BIND_HOST = "0.0.0.0"
MCP_BIND_PORT = 8765


def start_mcp_server() -> None:
    """Start the MCP server.  Only call this if MCP is enabled in config."""
    log.info("HostHive MCP Server starting on %s:%d", MCP_BIND_HOST, MCP_BIND_PORT)
    uvicorn.run(
        mcp_app,
        host=MCP_BIND_HOST,
        port=MCP_BIND_PORT,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    start_mcp_server()
