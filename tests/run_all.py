"""Runs all the tests:  .venv/bin/python tests/run_all.py"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS = ["test_textbox", "test_ink_equiv", "test_shapes", "test_backgrounds", "test_collaboration",
         "test_saving", "test_security"]


def main():
    failed = []
    for name in TESTS:
        r = subprocess.run([sys.executable, str(HERE / f"{name}.py")], capture_output=True, text=True)
        lines = [l for l in (r.stdout + r.stderr).splitlines() if l and not l.startswith("Database")]
        print(("OK      " if r.returncode == 0 else "FALLITO ") + (lines[0] if r.returncode == 0 else name))
        if r.returncode != 0:
            failed.append(name)
            print("\n".join("        " + l for l in lines[-8:]))
    print("\nTutti i test superati." if not failed else f"\nTest falliti: {', '.join(failed)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
