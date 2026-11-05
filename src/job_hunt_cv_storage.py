"""Atomic CV writes beneath a configured root, without following descendants."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import uuid


def write_cv_text(root: Path, relative_path: Path | str, text: str) -> Path:
    """Trust the canonical configured root; reject all descendant symlinks.

    Directory descriptors anchor traversal and replacement, so swapping a path
    for a symlink cannot redirect the write. An explicitly configured root may
    itself be a symlink. Return its original spelling for caller compatibility.
    """
    root = Path(root)
    relative = Path(relative_path)
    if relative.is_absolute() or not relative.parts or any(part in {".", ".."} for part in relative.parts):
        raise ValueError("CV destination must be relative to its configured root")
    encoded = text.encode("utf-8")
    canonical_root = root.resolve()
    canonical_root.mkdir(parents=True, exist_ok=True)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory_fd = os.open(canonical_root, directory_flags)
    temporary = None
    try:
        for part in relative.parts[:-1]:
            try:
                child_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=directory_fd)
                except FileExistsError:
                    pass
                child_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd

        name = relative.name

        def existing_mode() -> int | None:
            try:
                entry = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                return None
            if not stat.S_ISREG(entry.st_mode):
                raise ValueError("CV destination must be a regular file, not a symlink")
            return stat.S_IMODE(entry.st_mode)

        mode = existing_mode()
        candidate = f".{name}.{uuid.uuid4().hex}.tmp"
        file_fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                          0o600, dir_fd=directory_fd)
        temporary = candidate
        with os.fdopen(file_fd, "wb") as stream:
            if mode is not None:
                os.fchmod(stream.fileno(), mode)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        existing_mode()  # Refuse a symlink introduced while preparing the file.
        os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        temporary = None
    finally:
        try:
            if temporary is not None:
                os.unlink(temporary, dir_fd=directory_fd)
        finally:
            os.close(directory_fd)
    return root / relative
