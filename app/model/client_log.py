"""MODEL — log of the errors reported by the browsers (iPad).

Errors happening in Safari on the iPad cannot be seen from the computer: the
interface reports them and they are written here, in the internal data folder
(client-errors.log), to find out what went wrong. The file never grows beyond
MAX_BYTES: when full, the older half is dropped.
"""
import datetime as dt
import threading
from pathlib import Path

MAX_BYTES = 256 * 1024
_lock = threading.Lock()


class ClientLog:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "client-errors.log"

    def append(self, username: str, text: str):
        line = f"{dt.datetime.now().isoformat(timespec='seconds')}  {username}  {text}\n"
        with _lock:
            try:
                if self.path.exists() and self.path.stat().st_size > MAX_BYTES:
                    data = self.path.read_bytes()
                    self.path.write_bytes(data[len(data) // 2:].split(b"\n", 1)[-1])
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line)
                self.path.chmod(0o600)
            except OSError:
                pass     # a log that cannot be written must not disturb the app
