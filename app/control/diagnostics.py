"""CONTROL — errors reported by the interface in the browser.

The view on the iPad reports its unexpected errors (see app.js); the controller
cleans them (length, characters) and limits how many each user can send, then
the model writes them in the log on the computer.
"""
import re
import threading
import time

from ..model.client_log import ClientLog

MAX_FIELD = 2000                # characters kept for each field
MAX_PER_MINUTE = 10             # reports accepted per user per minute
FIELDS = ("message", "source", "stack", "page", "agent")
_UNSAFE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class DiagnosticsController:
    def __init__(self, log: ClientLog):
        self.log = log
        self.lock = threading.Lock()
        self.recent = {}        # username -> times of the last reports

    def report_error(self, username: str, data) -> None:
        if not isinstance(data, dict):
            return
        now = time.monotonic()
        with self.lock:
            times = [t for t in self.recent.get(username, []) if now - t < 60]
            if len(times) >= MAX_PER_MINUTE:
                self.recent[username] = times
                return          # too many: the first ones are enough to understand
            times.append(now)
            self.recent[username] = times
        parts = []
        for key in FIELDS:
            value = data.get(key)
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                text = _UNSAFE.sub(" ", str(value))[:MAX_FIELD].replace("\n", " | ")
                parts.append(f"{key}={text}")
        if parts:
            self.log.append(username, "  ".join(parts))
