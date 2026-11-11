"""Runs all the tests:  .venv/bin/python tests/run_all.py
The editor's JavaScript tests (tests/js) run with Node when it is installed; otherwise they are skipped."""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS = ["test_textbox", "test_ink_equiv", "test_shapes", "test_backgrounds", "test_collaboration",
         "test_saving", "test_security", "test_server_mode", "test_sync", "test_editor_extras"]
JS_TESTS = ["test_regions", "test_pencil", "test_queue"]


def main():
    failed = []
    for name in TESTS:
        r = subprocess.run([sys.executable, str(HERE / f"{name}.py")], capture_output=True, text=True)
        lines = [l for l in (r.stdout + r.stderr).splitlines() if l and not l.startswith("Database")]
        summary = next((l for l in lines if "controlli superati" in l), name)
        print(("OK      " if r.returncode == 0 else "FALLITO ") + (summary if r.returncode == 0 else name))
        if r.returncode != 0:
            failed.append(name)
            print("\n".join("        " + l for l in lines[-8:]))
    node = shutil.which("node")
    for name in JS_TESTS:
        if not node:
            print(f"SALTATO {name} (JavaScript): Node non installato")
            continue
        r = subprocess.run([node, "--import", str(HERE / "js" / "register.mjs"), str(HERE / "js" / f"{name}.mjs")],
                           capture_output=True, text=True, cwd=HERE.parent)
        lines = [l for l in (r.stdout + r.stderr).splitlines() if l]
        print(("OK      " if r.returncode == 0 else "FALLITO ") + (lines[-1] if r.returncode == 0 and lines else f"{name} (JavaScript)"))
        if r.returncode != 0:
            failed.append(name)
            print("\n".join("        " + l for l in lines[-8:]))
    print("\nTutti i test superati." if not failed else f"\nTest falliti: {', '.join(failed)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
