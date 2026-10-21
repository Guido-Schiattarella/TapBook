"""MODEL — file operations shared by the whole model, the same on Linux and Windows.

  * atomic_write: writes a file atomically (temporary file in the same folder,
    then replacement): the disk always holds either the old version or the
    complete new one, never half of it;
  * replace: the replacement itself. On Windows a file opened by another
    program (antivirus, indexer, a PDF reader) cannot be replaced for a few
    moments: it is retried for a couple of seconds;
  * is_link: symbolic links and, on Windows, "junctions" (folder links),
    which the app never follows.
"""
import os
import tempfile
import time
from pathlib import Path

RETRY_SECONDS = 2.0


class FileBusy(OSError):
    """The file is in use by another program and could not be replaced."""


def replace(src, dst):
    deadline = time.monotonic() + RETRY_SECONDS
    while True:
        try:
            os.replace(src, dst)
            return
        except PermissionError as e:
            if os.name != "nt" or time.monotonic() > deadline:
                raise FileBusy(e.errno, f"File in uso da un altro programma: {Path(dst).name}") from e
            time.sleep(0.1)


def atomic_write(path: Path, data: bytes, fsync: bool = True):
    fd, tmp = tempfile.mkstemp(prefix=".~", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            if fsync:
                fh.flush()
                os.fsync(fh.fileno())
        replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def is_link(path) -> bool:
    path = Path(path)
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
