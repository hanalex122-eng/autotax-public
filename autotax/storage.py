"""Local file storage for invoice originals.

Files are written to UPLOADS_DIR/{user_id}/{yyyy}/{mm}/{uuid}.{ext}
and only the relative path is stored in the database.

This replaces storing the file bytes as a Postgres BLOB (file_data column),
which caused the database disk to fill up.
"""
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("autotax")

UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", "./data/uploads")).resolve()


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _safe_ext(filename: str | None) -> str:
    if not filename:
        return ".bin"
    ext = os.path.splitext(filename)[1].lower()
    # Allow only common invoice/image extensions
    allowed = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif",
               ".pdf", ".xml", ".heic", ".gif"}
    return ext if ext in allowed else ".bin"


def save_file(user_id: int, content: bytes, filename: str | None = None) -> str:
    """Write bytes to disk under the user's directory.
    Returns a *relative* path (relative to UPLOADS_DIR) to store in the DB.
    """
    if not isinstance(content, (bytes, bytearray)):
        raise ValueError("content must be bytes")

    now = datetime.now(timezone.utc)
    sub = Path(str(int(user_id))) / f"{now.year:04d}" / f"{now.month:02d}"
    dir_abs = UPLOADS_DIR / sub
    _ensure_dir(dir_abs)

    name = f"{uuid.uuid4().hex}{_safe_ext(filename)}"
    dest = dir_abs / name
    tmp = dest.with_suffix(dest.suffix + ".tmp")

    # Atomic write: write to .tmp, then rename
    with open(tmp, "wb") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, dest)

    rel = (sub / name).as_posix()
    logger.info("Stored file: %s (%d bytes)", rel, len(content))
    return rel


def _resolve(rel_path: str) -> Path:
    """Resolve a stored relative path safely under UPLOADS_DIR.
    Refuses any path that escapes the base directory.
    """
    if not rel_path or rel_path.startswith(("/", "\\")) or ".." in Path(rel_path).parts:
        raise ValueError("invalid file path")
    abs_path = (UPLOADS_DIR / rel_path).resolve()
    # Must stay inside UPLOADS_DIR
    try:
        abs_path.relative_to(UPLOADS_DIR)
    except ValueError as exc:
        raise ValueError("path traversal detected") from exc
    return abs_path


def read_file(rel_path: str) -> bytes:
    with open(_resolve(rel_path), "rb") as f:
        return f.read()


def file_exists(rel_path: str) -> bool:
    try:
        return _resolve(rel_path).is_file()
    except ValueError:
        return False


def delete_file(rel_path: str) -> bool:
    try:
        p = _resolve(rel_path)
    except ValueError:
        return False
    if p.is_file():
        try:
            p.unlink()
            return True
        except OSError as e:
            logger.warning("Failed to delete %s: %s", rel_path, e)
    return False
