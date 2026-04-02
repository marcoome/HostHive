"""File manager router -- /api/v1/files.

SECURITY: All paths are sandboxed within /home/{username}/ to prevent
path traversal attacks. Every path is resolved and validated before use.

LOCAL FALLBACK: Every file operation first attempts to use the agent
(port 7080). If the agent is unreachable or returns an error, the
endpoint falls back to direct filesystem operations using Python's
os / shutil / stat modules. This ensures the File Manager remains
functional even when the agent process is down.
"""

from __future__ import annotations

import base64
import datetime
import os
import posixpath
import pwd
import shutil
import stat
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
from api.schemas.files import FileItem, FileListResponse, FileWriteRequest

router = APIRouter()


# --------------------------------------------------------------------------
# Path security
# --------------------------------------------------------------------------

def _safe_path(username: str, path: str) -> str:
    """Resolve and validate a path to ensure it stays within the user sandbox.

    Raises HTTPException 403 on traversal attempt.
    """
    sandbox = f"/home/{username}"
    # If path already starts with the sandbox, use it directly
    if path.startswith(sandbox + "/") or path == sandbox:
        normalized = posixpath.normpath(path)
    else:
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
        # Allow /home itself and any path under /home/
        if normalized == "/home":
            return normalized
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
# Local filesystem helpers
# --------------------------------------------------------------------------

def _format_permissions(mode: int) -> str:
    """Return octal permission string like '0755'."""
    return oct(stat.S_IMODE(mode))


def _get_owner(st: os.stat_result) -> str:
    """Return the username that owns the file, or UID as string."""
    try:
        return pwd.getpwuid(st.st_uid).pw_name
    except (KeyError, OverflowError):
        return str(st.st_uid)


def _stat_to_file_item(entry_path: str, entry_name: str) -> FileItem:
    """Build a FileItem from an os.stat() call."""
    try:
        st = os.stat(entry_path)
    except OSError:
        return FileItem(name=entry_name, path=entry_path, is_dir=False)

    return FileItem(
        name=entry_name,
        path=entry_path,
        is_dir=stat.S_ISDIR(st.st_mode),
        size=st.st_size,
        modified=datetime.datetime.fromtimestamp(st.st_mtime, tz=datetime.timezone.utc).isoformat(),
        permissions=_format_permissions(st.st_mode),
        owner=_get_owner(st),
    )


def _local_list_files(directory: str) -> list[dict]:
    """List files in *directory* using os.listdir + os.stat."""
    items: list[dict] = []
    try:
        entries = sorted(os.listdir(directory))
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Directory not found: {directory}")
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Permission denied: {directory}")

    for name in entries:
        full = os.path.join(directory, name)
        item = _stat_to_file_item(full, name)
        items.append(item.model_dump())
    return items


def _local_read_file(filepath: str) -> dict:
    """Read a file and return content + encoding."""
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File not found: {filepath}")
    try:
        with open(filepath, "rb") as fh:
            raw = fh.read()
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Permission denied: {filepath}")

    # Try UTF-8 first; fall back to base64 for binary content
    try:
        content = raw.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        content = base64.b64encode(raw).decode("ascii")
        encoding = "base64"

    return {"content": content, "encoding": encoding}


def _local_write_file(filepath: str, content: str, encoding: str = "utf-8") -> None:
    """Write content to a file on disk."""
    parent = os.path.dirname(filepath)
    if parent and not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except PermissionError:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Permission denied creating parent dirs: {parent}")

    try:
        if encoding == "base64":
            data = base64.b64decode(content)
            with open(filepath, "wb") as fh:
                fh.write(data)
        else:
            with open(filepath, "w", encoding="utf-8") as fh:
                fh.write(content)
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Permission denied: {filepath}")


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
# GET /tree -- file tree using os.scandir
# --------------------------------------------------------------------------
@router.get("/tree", status_code=status.HTTP_200_OK)
async def get_file_tree(
    path: str = Query("/", max_length=4096),
    current_user: User = Depends(get_current_user),
):
    """Return a one-level directory tree for the given path."""
    # Default to user's home directory if path is root and user is not admin
    if path == "/" and not _is_admin(current_user):
        path = f"/home/{current_user.username}"
    elif path == "/" and _is_admin(current_user):
        path = "/home"
    safe = _resolve_path(current_user, path)
    tree: list[dict] = []
    try:
        for entry in os.scandir(safe):
            node: dict = {
                "name": entry.name,
                "path": os.path.join(safe, entry.name),
                "is_dir": entry.is_dir(),
            }
            if entry.is_dir():
                node["children"] = []  # Lazy load
            tree.append(node)
    except Exception:
        pass
    return {"path": safe, "children": tree}


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

    # --- Try agent first ---
    try:
        result = await agent.list_files(safe)
        return FileListResponse(
            path=safe,
            items=result.get("items", []),
            total=len(result.get("items", [])),
        )
    except Exception:
        pass

    # --- Fallback: local filesystem ---
    # Create user home directory if it doesn't exist
    if not os.path.exists(safe):
        try:
            os.makedirs(safe, mode=0o755, exist_ok=True)
        except OSError:
            pass
    if not os.path.exists(safe):
        return FileListResponse(path=safe, items=[], total=0)
    items = _local_list_files(safe)
    return FileListResponse(path=safe, items=items, total=len(items))


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

    # --- Try agent first ---
    try:
        agent = request.app.state.agent
        # Try UTF-8 for text files, fall back to base64 for binary
        try:
            text_content = content.decode("utf-8")
        except UnicodeDecodeError:
            text_content = base64.b64encode(content).decode("ascii")
        await agent.write_file(safe_dest, text_content)
    except Exception:
        # --- Fallback: local filesystem ---
        try:
            os.makedirs(safe_dir, exist_ok=True)
            with open(safe_dest, "wb") as fh:
                fh.write(content)
        except PermissionError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied writing to {safe_dest}",
            )
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error uploading file: {exc}",
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

    # --- Try agent first ---
    try:
        agent = request.app.state.agent
        result = await agent.read_file(safe)
        return {
            "path": safe,
            "content": result.get("content", ""),
            "encoding": result.get("encoding", "utf-8"),
        }
    except Exception:
        pass

    # --- Fallback: local filesystem ---
    result = _local_read_file(safe)
    return {
        "path": safe,
        "content": result["content"],
        "encoding": result["encoding"],
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

    # --- Try agent first ---
    try:
        agent = request.app.state.agent
        await agent._request("POST", "/files/mkdir", json_body={"path": safe})
    except Exception:
        # --- Fallback: local filesystem ---
        try:
            os.makedirs(safe, exist_ok=True)
        except PermissionError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied creating directory: {safe}",
            )
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error creating directory: {exc}",
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

    # --- Try agent first ---
    try:
        agent = request.app.state.agent
        await agent._request(
            "POST",
            "/files/rename",
            json_body={"old_path": safe_old, "new_path": safe_new},
        )
    except Exception:
        # --- Fallback: local filesystem ---
        if not os.path.exists(safe_old):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source path not found: {safe_old}",
            )
        try:
            os.rename(safe_old, safe_new)
        except PermissionError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied renaming {safe_old}",
            )
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error renaming: {exc}",
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

    # --- Try agent first ---
    try:
        agent = request.app.state.agent
        await agent._request("DELETE", "/files", json_body={"path": safe})
    except Exception:
        # --- Fallback: local filesystem ---
        if not os.path.exists(safe):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Path not found: {safe}",
            )
        try:
            if os.path.isdir(safe):
                shutil.rmtree(safe)
            else:
                os.remove(safe)
        except PermissionError:
            # Try with sudo
            import subprocess
            try:
                subprocess.run(["sudo", "rm", "-rf", safe], check=True, timeout=10)
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission denied deleting {safe}",
                )
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error deleting: {exc}",
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

    # --- Try agent first ---
    try:
        agent = request.app.state.agent
        result = await agent.read_file(safe)
        return {"path": safe, "content": result.get("content", "")}
    except Exception:
        pass

    # --- Fallback: local filesystem ---
    result = _local_read_file(safe)
    return {"path": safe, "content": result["content"]}


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

    # --- Try agent first ---
    try:
        agent = request.app.state.agent
        await agent.write_file(safe, body.content)
    except Exception:
        # --- Fallback: local filesystem ---
        _local_write_file(safe, body.content, body.encoding)

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

    # --- Try agent first ---
    try:
        agent = request.app.state.agent
        await agent._request(
            "POST",
            "/files/chmod",
            json_body={"path": safe, "permissions": body.permissions},
        )
    except Exception:
        # --- Fallback: local filesystem ---
        if not os.path.exists(safe):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Path not found: {safe}",
            )
        try:
            mode = int(body.permissions, 8)
            os.chmod(safe, mode)
        except PermissionError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied changing permissions on {safe}",
            )
        except (ValueError, OSError) as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error changing permissions: {exc}",
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
