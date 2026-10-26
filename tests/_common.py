"""Shared helpers of the tests (temporary library, controller)."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.control.editing import EditController  # noqa: E402
from app.control.library import LibraryController  # noqa: E402


class Checks:
    def __init__(self, name):
        self.name, self.ok = name, 0

    def __call__(self, cond, msg):
        assert cond, msg
        self.ok += 1

    def done(self, extra=""):
        print(f"{self.name}: {self.ok} controlli superati{(' ' + extra) if extra else ''}")


def workspace(*users):
    tmp = Path(tempfile.mkdtemp())
    for u in users or ("anna",):
        (tmp / "notes" / u).mkdir(parents=True)
    lib = LibraryController(tmp / "notes")
    ed = EditController(lib, tmp / "cache", 15, tmp / "backgrounds")
    return tmp, lib, ed
