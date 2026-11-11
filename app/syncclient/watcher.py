"""TapBook Sync — the operating system tells when something changes in the
folder, instead of looking at it every 2 seconds: changes are noticed at once and
nothing is spent while the folder is still.

  Linux    inotify (one watch per folder, added as folders appear)
  Windows  ReadDirectoryChangesW on the whole tree

Only the standard library (ctypes). If the system refuses (too many folders for
inotify's limit, a network drive, another system), start() returns False and
the service goes back to looking every few seconds. Even when it works, the
service still looks at the whole folder now and then, in case an event was lost.
"""
import ctypes
import os
import select
import struct
import threading
from pathlib import Path


class Watcher:
    """Calls `on_change()` (from a thread of its own) when something changes."""

    def __init__(self, root: Path, on_change):
        self.root = Path(root)
        self.on_change = on_change
        self.stopped = False

    def start(self) -> bool:
        try:
            if os.name == "nt":
                ok = self._start_windows()
            elif os.uname().sysname == "Linux":
                ok = self._start_inotify()
            else:
                ok = False
        except Exception:
            ok = False
        return ok

    def stop(self):
        self.stopped = True

    # --- Linux: inotify ------------------------------------------------------------------------------
    IN_MODIFY, IN_ATTRIB, IN_CLOSE_WRITE = 0x002, 0x004, 0x008
    IN_MOVED_FROM, IN_MOVED_TO, IN_CREATE, IN_DELETE = 0x040, 0x080, 0x100, 0x200
    IN_DELETE_SELF, IN_MOVE_SELF, IN_Q_OVERFLOW, IN_IGNORED, IN_ISDIR = 0x400, 0x800, 0x4000, 0x8000, 0x40000000
    MASK = (IN_MODIFY | IN_ATTRIB | IN_CLOSE_WRITE | IN_MOVED_FROM | IN_MOVED_TO | IN_CREATE | IN_DELETE
            | IN_DELETE_SELF | IN_MOVE_SELF)

    def _start_inotify(self) -> bool:
        libc = ctypes.CDLL(None, use_errno=True)
        self._libc = libc
        self._fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self._fd < 0:
            return False
        self._dirs = {}                       # watch descriptor → folder
        if not self._watch_tree(self.root):
            os.close(self._fd)
            return False
        threading.Thread(target=self._inotify_loop, daemon=True, name="cartella").start()
        return True

    def _watch_tree(self, top: Path) -> bool:
        for dirpath, dirnames, _ in os.walk(top):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")
                           and not os.path.islink(os.path.join(dirpath, d))]
            wd = self._libc.inotify_add_watch(self._fd, os.fsencode(dirpath), self.MASK)
            if wd < 0:
                return False                  # e.g. the system's limit of watched folders
            self._dirs[wd] = Path(dirpath)
        return True

    def _inotify_loop(self):
        header = struct.calcsize("iIII")
        while not self.stopped:
            ready, _, _ = select.select([self._fd], [], [], 1.0)
            if not ready:
                continue
            try:
                data = os.read(self._fd, 64 * 1024)
            except BlockingIOError:
                continue
            except OSError:
                break
            changed, offset = False, 0
            while offset + header <= len(data):
                wd, mask, _, length = struct.unpack_from("iIII", data, offset)
                name = data[offset + header:offset + header + length].rstrip(b"\0").decode("utf-8", "replace")
                offset += header + length
                if mask & self.IN_IGNORED:
                    self._dirs.pop(wd, None)
                    continue
                if name.startswith("."):
                    continue                  # hidden: not synchronised (and our own .tapbook-sync)
                changed = True
                if mask & self.IN_ISDIR and mask & (self.IN_CREATE | self.IN_MOVED_TO) and wd in self._dirs:
                    self._watch_tree(self._dirs[wd] / name)      # a new folder: watched too
            if changed or len(data) == 0:
                self.on_change()
        os.close(self._fd)

    # --- Windows: ReadDirectoryChangesW ------------------------------------------------------------
    def _start_windows(self) -> bool:
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel32.CreateFileW
        create.restype = wintypes.HANDLE
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                           wintypes.DWORD, wintypes.HANDLE]
        handle = create(str(self.root), 0x0001,               # FILE_LIST_DIRECTORY
                        0x1 | 0x2 | 0x4,                      # share read, write, delete
                        None, 3, 0x02000000, None)            # OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS
        if handle in (None, wintypes.HANDLE(-1).value):
            return False
        read = kernel32.ReadDirectoryChangesW
        read.restype = wintypes.BOOL
        read.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
                         ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID, wintypes.LPVOID]
        flags = 0x1 | 0x2 | 0x8 | 0x10        # file name, folder name, size, last write

        def loop():
            buffer = ctypes.create_string_buffer(64 * 1024)
            returned = wintypes.DWORD()
            while not self.stopped:
                ok = read(handle, buffer, len(buffer), True, flags, ctypes.byref(returned), None, None)
                if not ok:
                    break                     # folder removed or the drive went away: looking resumes
                if not self._windows_only_hidden(buffer, returned.value):
                    self.on_change()
            kernel32.CloseHandle(handle)
        threading.Thread(target=loop, daemon=True, name="cartella").start()
        return True

    @staticmethod
    def _windows_only_hidden(buffer, size) -> bool:
        """True if every change reported is inside a hidden item (.tapbook-sync)."""
        if size == 0:
            return False                      # buffer overflow: something changed, look at everything
        offset = 0
        while True:
            next_offset, _, length = struct.unpack_from("III", buffer, offset)
            name = buffer.raw[offset + 12:offset + 12 + length].decode("utf-16-le", "replace")
            if not any(part.startswith(".") for part in name.replace("\\", "/").split("/")):
                return False
            if not next_offset:
                return True
            offset += next_offset
