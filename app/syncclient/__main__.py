"""TapBook Sync from the command line:

    python -m app.syncclient              the window
    python -m app.syncclient service      the background service
    python -m app.syncclient status       what the service is doing
    python -m app.syncclient autostart [--no-start]   start the service at every login (and now)
    python -m app.syncclient no-autostart stop starting it at login
"""
import sys
import time


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = (argv if argv is not None else sys.argv[1:]) or ["window"]
    command = args[0]
    if command == "window":
        from .window import main as window
        window(check="--check" in args)
    elif command == "service":
        from .service import main as service
        service()
    elif command == "status":
        from . import settings
        from .service import running
        cfg = settings.load()
        status = settings.read_json(settings.status_path(), {})
        print(f"Server:    {cfg['server'] or '-'}  ({'collegato' if settings.load_token() else 'non collegato'})")
        print(f"Cartella:  {cfg['folder'] or '-'}")
        print(f"Servizio:  {'in esecuzione' if running() else 'fermo'}")
        print(f"Stato:     {status.get('message', '-')}")
        for r in (status.get("recent") or [])[-10:]:
            print(f"  {time.strftime('%H:%M:%S', time.localtime(r['t']))}  {r['text']}")
    elif command == "autostart":
        # --no-start: only at the next login (the Windows installer runs as
        # administrator: the service must not start with those rights)
        from .service import install_autostart
        install_autostart(start="--no-start" not in args)
        print("TapBook Sync parte a ogni accesso.")
    elif command == "no-autostart":
        from .service import remove_autostart
        remove_autostart()
        print("TapBook Sync non parte più all'accesso.")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
