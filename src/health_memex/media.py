"""Source-asset file storage and path resolution.

``source_assets.file_path`` holds one of two forms:

- an **absolute** path, for assets discovered in an EHR export by the
  source loaders (Epic, MEDITECH, athena, MyChart). These point at the
  user's original export files and are returned unchanged.
- a path **relative to the directory containing the database**, for
  assets restored by arkiv import. Import copies every asset's bytes into
  ``<db dir>/media/<unique_id>.<ext>`` so the archive owns its media and
  no longer depends on the bundle (or a temporary extraction of it).

Files are named by the row's durable ``unique_id``, not by content hash:
``UNIQUE(source, file_path)`` and ``unique_id`` are the table's identity
contract, so byte-identical assets on distinct rows are stored once per
row rather than deduplicated.

:func:`resolve_asset_path` is the single place that turns a stored
``file_path`` into a filesystem path. Every reader goes through it.
"""

from __future__ import annotations

import contextlib
import filecmp
import os
import tempfile
from pathlib import Path, PurePath

from health_memex.db import _is_unique_id_format

MEDIA_DIRNAME = "media"


class MediaStoreError(ValueError):
    """An asset file could not be stored safely."""


def db_directory(db_path: str | os.PathLike[str] | None) -> Path | None:
    """Directory holding the database file, or None for in-memory/URI DBs."""
    if db_path is None:
        return None
    s = os.fspath(db_path)
    if s in ("", ":memory:") or s.startswith("file:"):
        return None
    return Path(os.path.abspath(s)).parent


def resolve_asset_path(db_path: str | os.PathLike[str] | None, file_path: str) -> Path | None:
    """Resolve a stored ``source_assets.file_path`` to a filesystem path.

    Absolute paths are returned as-is. Relative paths are resolved against
    the database's directory and must stay inside it (including through
    symlinks). Returns None when the path is empty, relative with no
    database directory to anchor it, or escapes that directory.
    """
    if not file_path:
        return None
    p = Path(file_path)
    if p.is_absolute():
        return p
    base = db_directory(db_path)
    if base is None:
        return None
    resolved = (base / p).resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError:
        return None
    return resolved


def media_root(db_path: str | os.PathLike[str] | None, media_dir: str | None = None) -> Path:
    """Directory imported media is written to.

    *media_dir* when given, else ``<db dir>/media``. Raises
    :class:`MediaStoreError` for a database with no directory (``:memory:``)
    and no explicit *media_dir*.
    """
    if media_dir is not None:
        return Path(os.path.abspath(media_dir))
    base = db_directory(db_path)
    if base is None:
        raise MediaStoreError(
            f"database {os.fspath(db_path) if db_path is not None else None!r} has no "
            "directory to store imported media in; pass an explicit media_dir"
        )
    return base / MEDIA_DIRNAME


def media_file_name(unique_id: object, original_name: str) -> str:
    """``<unique_id>.<ext>`` for an asset, ext lowercased from *original_name*.

    *unique_id* must be a durable-ID hex string; anything else is rejected
    rather than sanitized, since it becomes a filename. An extension that
    is not plain ASCII alphanumerics is dropped.
    """
    if not isinstance(unique_id, str) or not _is_unique_id_format(unique_id):
        raise MediaStoreError(f"invalid unique_id for a media file name: {unique_id!r}")
    ext = PurePath(original_name or "").suffix.lower()
    stem = ext[1:]
    if not (stem.isascii() and stem.isalnum()):
        ext = ""
    return unique_id + ext


def stored_file_path(db_path: str | os.PathLike[str] | None, path: Path) -> str:
    """The ``file_path`` value to store for *path*: relative (POSIX) to the
    DB directory when inside it, otherwise absolute."""
    base = db_directory(db_path)
    if base is not None:
        try:
            return path.resolve().relative_to(base.resolve()).as_posix()
        except ValueError:
            pass
    return str(path.resolve())


def store_media(root: Path, name: str, data: bytes) -> Path:
    """Atomically write *data* to ``root/name`` and return that path.

    Writes a temp file in *root*, then ``os.replace``. If the destination
    already holds identical bytes it is left untouched; different bytes are
    replaced (the caller's content is authoritative). Refuses a symlinked
    *root* or destination and any *name* that is not a plain basename.
    """
    if not name or name in (".", "..") or PurePath(name).name != name:
        raise MediaStoreError(f"media file name must be a plain basename: {name!r}")
    if root.is_symlink():
        raise MediaStoreError(f"refusing to write media through symlinked directory {root}")
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise MediaStoreError(f"media path is not a directory: {root}")
    dest = root / name
    if dest.is_symlink():
        raise MediaStoreError(f"refusing to overwrite symlink {dest}")
    if dest.exists() and not dest.is_file():
        raise MediaStoreError(f"media destination is not a regular file: {dest}")

    fd, tmp = tempfile.mkstemp(dir=root, prefix=".incoming-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if dest.is_file() and filecmp.cmp(tmp, dest, shallow=False):
            os.unlink(tmp)
        else:
            os.replace(tmp, dest)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return dest
