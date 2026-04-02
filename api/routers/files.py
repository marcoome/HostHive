"""File manager router -- /api/v1/files.

SECURITY: All paths are sandboxed within /home/{username}/ to prevent
path traversal attacks. Every path is resolved and validated before use.
"""

from __future__ import annotations

import base64
import os
import posixpath
import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.rate_limit import limiter
from api.core.security import get_current_user
from api.models.activity_log import ActivityLog
from api.models.users import User
from api.schemas.files import FileListResponse, FileWriteRequest

router = APIRouter()


# --------------------------------------------------------------------------
# Path security
# --------------------------------------------------------------------------

def _safe_path(username: str, path: str) -> str:
    """Resolve and validate a path to ensure it stays within the user sandbox.

    Raises HTTPException 403 on traversal attempt.
    """
    sandbox = f"/home/{username}"
    # Normalize: collapse .., resolve ~, strip trailing slashes
    normalized = posixpath.normpath(posixpath.join(sandbox, path.lstrip("/")))
    # Ensure the final path starts with the sandbox
    if not (normalized == sandbox or normalized.startswith(sandbox + "/")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Path traversal detected: access denied.",
        )
    return normalized


def _is_admin(user: User) -> bool:
    return user.role.value == "admin"


def _resolve_path(current_user: User, raw_path: str) -> str:
    """Admins can access any /home/ path; users are sandboxed."""
    if _is_admin(current_user):
        normalized = posixpath.normpath(raw_path)
        if not normalized.startswith("/home/"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="File access is restricted to /home/.",
            )
        return normalized
    return _safe_path(current_user.username, raw_path)


def _log(db: AsyncSession, request: Request, user_id: uuid.UUID, action: str, details: str):
    client_ip = request.client.host if request.client else "unknown"
    db.add(ActivityLog(user_id=user_id, action=action, details=details, ip_address=client_ip))


# --------------------------------------------------------------------------
# Request body models
# --------------------------------------------------------------------------

class CreateDirRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=4096)


class RenameRequest(BaseModel):
    old_path: str = Field(..., min_length=1, max_length=4096)
    new_path: str = Field(..., min_length=1, max_length=4096)


class DeleteRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=4096)


class ChmodRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=4096)
    permissions: str = Field(..., pattern=r"^[0-7]{3,4}$")


class CompressRequest(BaseModel):
    paths: list[str] = Field(..., min_length=1)
    destination: str = Field(..., min_length=1, max_length=4096)


class ExtractRequest(BaseModel):
    archive_path: str = Field(..., min_length=1, max_length=4096)
    destination: str = Field(..., min_length=1, max_length=4096)


# --------------------------------------------------------------------------
# GET /tree -- file tree stub for frontend compatibility
# --------------------------------------------------------------------------
@router.get("/tree", status_code=status.HTTP_200_OK)
async def get_file_tree(
    path: str = Query("/", max_length=4096),
    current_user: User = Depends(get_current_user),
):
    """Stub for file tree - returns empty tree."""
    return {"path": path, "children": []}


# --------------------------------------------------------------------------
# GET /list -- directory listing
# --------------------------------------------------------------------------
@router.get("/list", response_model=FileListResponse, status_code=status.HTTP_200_OK)
async def list_files(
    path: str = Query("/", max_length=4096),
    request: Request = None,
    current_user: User = Depends(get_current_user),
):
    safe = _resolve_path(current_user, path)
    agent = request.app.state.agent

    try:
        result = await agent.list_files(safe)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error listing files: {exc}",
        )

    return FileListResponse(
        path=safe,
        items=result.get("items", []),
        total=len(result.get("items", [])),
    )


# --------------------------------------------------------------------------
# POST /upload -- multipart file upload
# --------------------------------------------------------------------------
@router.post("/upload", status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def upload_file(
    file: UploadFile,
    path: str = Query(..., max_length=4096),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    safe_dir = _resolve_path(current_user, path)
    safe_dest = posixpath.join(safe_dir, file.filename)
    # Re-validate the final destination
    _resolve_path(current_user, safe_dest)

    content = await file.read()
    agent = request.app.state.agent

    # Try UTF-8 for text files, fall back to base64 for binary
    try:
        text_content = content.decode("utf-8")
    except UnicodeDecodeError:
        text_content = base64.b64encode(content).decode("ascii")

    try:
        await agent.write_file(safe_dest, text_content)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error uploading file: {exc}",
        )

    _log(db, request, current_user.id, "files.upload", f"Uploaded {file.filename} to {safe_dir}")
    return {"detail": "File uploaded.", "path": safe_dest}


# --------------------------------------------------------------------------
# GET /download -- file download
# --------------------------------------------------------------------------
@router.get("/download", status_code=status.HTTP_200_OK)
async def download_file(
    path: str = Query(..., max_length=4096),
    request: Request = None,
    current_user: User = Depends(get_current_user),
):
    safe = _resolve_path(current_user, path)
    agent = request.app.state.agent

    try:
        result = await agent.read_file(safe)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error reading file: {exc}",
        )

    return {
        "path": safe,
        "content": result.get("content", ""),
        "encoding": result.get("encoding", "utf-8"),
    }


# --------------------------------------------------------------------------
# POST /create-dir
# --------------------------------------------------------------------------
@router.post("/create-dir", status_code=status.HTTP_201_CREATED)
async def create_directory(
    body: CreateDirRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    safe = _resolve_path(current_user, body.path)
    agent = request.app.state.agent

    try:
        await agent._request("POST", "/files/mkdir", json_body={"path": safe})
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error creating directory: {exc}",
        )

    _log(db, request, current_user.id, "files.create_dir", f"Created directory {safe}")
    return {"detail": "Directory created.", "path": safe}


# --------------------------------------------------------------------------
# POST /rename
# --------------------------------------------------------------------------
@router.post("/rename", status_code=status.HTTP_200_OK)
async def rename_file(
    body: RenameRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    safe_old = _resolve_path(current_user, body.old_path)
    safe_new = _resolve_path(current_user, body.new_path)
    agent = request.app.state.agent

    try:
        await agent._request(
            "POST",
            "/files/rename",
            json_body={"old_path": safe_old, "new_path": safe_new},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error renaming: {exc}",
        )

    _log(db, request, current_user.id, "files.rename", f"Renamed {safe_old} -> {safe_new}")
    return {"detail": "Renamed.", "old_path": safe_old, "new_path": safe_new}


# --------------------------------------------------------------------------
# DELETE /delete
# --------------------------------------------------------------------------
@router.delete("/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    body: DeleteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    safe = _resolve_path(current_user, body.path)
    agent = request.app.state.agent

    try:
        await agent._request("DELETE", "/files", json_body={"path": safe})
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error deleting: {exc}",
        )

    _log(db, request, current_user.id, "files.delete", f"Deleted {safe}")


# --------------------------------------------------------------------------
# GET /read -- read file content
# --------------------------------------------------------------------------
@router.get("/read", status_code=status.HTTP_200_OK)
async def read_file(
    path: str = Query(..., max_length=4096),
    request: Request = None,
    current_user: User = Depends(get_current_user),
):
    safe = _resolve_path(current_user, path)
    agent = request.app.state.agent

    try:
        result = await agent.read_file(safe)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error reading file: {exc}",
        )

    return {"path": safe, "content": result.get("content", "")}


# --------------------------------------------------------------------------
# PUT /write -- write file content
# --------------------------------------------------------------------------
@router.put("/write", status_code=status.HTTP_200_OK)
async def write_file(
    body: FileWriteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    safe = _resolve_path(current_user, body.path)
    agent = request.app.state.agent

    try:
        await agent.write_file(safe, body.content)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error writing file: {exc}",
        )

    _log(db, request, current_user.id, "files.write", f"Wrote to {safe}")
    return {"detail": "File written.", "path": safe}


# --------------------------------------------------------------------------
# POST /chmod -- change permissions
# --------------------------------------------------------------------------
@router.post("/chmod", status_code=status.HTTP_200_OK)
async def chmod_file(
    body: ChmodRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    safe = _resolve_path(current_user, body.path)
    agent = request.app.state.agent

    try:
        await agent._request(
            "POST",
            "/files/chmod",
            json_body={"path": safe, "permissions": body.permissions},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error changing permissions: {exc}",
        )

    _log(db, request, current_user.id, "files.chmod", f"chmod {body.permissions} {safe}")
    return {"detail": "Permissions updated.", "path": safe, "permissions": body.permissions}


# --------------------------------------------------------------------------
# POST /compress -- zip files
# --------------------------------------------------------------------------
@router.post("/compress", status_code=status.HTTP_200_OK)
async def compress_files(
    body: CompressRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    safe_paths = [_resolve_path(current_user, p) for p in body.paths]
    safe_dest = _resolve_path(current_user, body.destination)
    agent = request.app.state.agent

    try:
        await agent._request(
            "POST",
            "/files/compress",
            json_body={"paths": safe_paths, "destination": safe_dest},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error compressing: {exc}",
        )

    _log(db, request, current_user.id, "files.compress", f"Compressed {len(safe_paths)} items to {safe_dest}")
    return {"detail": "Files compressed.", "destination": safe_dest}


# --------------------------------------------------------------------------
# POST /extract -- extract archive
# --------------------------------------------------------------------------
@router.post("/extract", status_code=status.HTTP_200_OK)
async def extract_archive(
    body: ExtractRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    safe_archive = _resolve_path(current_user, body.archive_path)
    safe_dest = _resolve_path(current_user, body.destination)
    agent = request.app.state.agent

    try:
        await agent._request(
            "POST",
            "/files/extract",
            json_body={"archive_path": safe_archive, "destination": safe_dest},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent error extracting: {exc}",
        )

    _log(db, request, current_user.id, "files.extract", f"Extracted {safe_archive} to {safe_dest}")
    return {"detail": "Archive extracted.", "destination": safe_dest}
