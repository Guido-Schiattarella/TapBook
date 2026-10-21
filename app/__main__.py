"""TapBook command line (same on Linux and Windows).

    python -m app desktop               control panel (window to start and stop the server)
    python -m app serve [--host H] [--port P]   runs the server in the terminal
    python -m app add-user <name>       creates a profile (asks for the password)
    python -m app passwd <name>         changes a password
    python -m app del-user <name>       deletes a profile (its folder stays on disk)
    python -m app list-users            lists the profiles
    python -m app init-db               creates the user database if missing
                                        (every command does it anyway)
    python -m app firewall-uninstall    (Linux) removes the firewall helper installed
                                        by earlier versions and its sudo rule

On Windows "python" is the virtual environment's Python: .venv\\Scripts\\python.
"""
import argparse
import getpass
import sys
import threading

from .config import load_config
from .control.errors import ControlError
from .security import password_problem


def _ask_password(username: str) -> str:
    while True:
        pw = getpass.getpass("Password: ")
        problem = password_problem(pw, username)
        if problem:
            print(problem)
            continue
        if pw != getpass.getpass("Ripeti password: "):
            print("Le password non coincidono.")
            continue
        return pw


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app", description="TapBook: note PDF per iPad")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    # Server started by the control panel: JSON messages, password and "stop"
    # command on standard input (see _controlled).
    serve.add_argument("--controlled", action="store_true", help=argparse.SUPPRESS)
    # --check: the installers verify that the panel starts (see app/desktop).
    sub.add_parser("desktop").add_argument("--check", action="store_true", help=argparse.SUPPRESS)
    for name in ("add-user", "passwd", "del-user"):
        sub.add_parser(name).add_argument("username")
    sub.add_parser("list-users")
    sub.add_parser("init-db")
    sub.add_parser("firewall-uninstall")
    return parser


def _user_command(args, config):
    from .bootstrap import build_auth
    auth = build_auth(config)
    if args.cmd == "init-db":
        print(f"Database degli utenti pronto. Cartella note: {config.notes_root}")
    elif args.cmd == "add-user":
        folder = auth.create_user(args.username, _ask_password(args.username))
        print(f"Utente creato. Cartella: {folder}")
    elif args.cmd == "passwd":
        auth.change_password(args.username, _ask_password(args.username))
        print("Password aggiornata.")
    elif args.cmd == "del-user":
        auth.delete_user(args.username)
        print("Utente eliminato. La cartella dei documenti NON è stata cancellata.")
    elif args.cmd == "list-users":
        for u in auth.list_users():
            print(f"{u['username']:<32} creato {u['created_at']}  ultimo accesso {u['last_login'] or '-'}")


def _controlled():
    """Server driven by the control panel through standard input: the first
    line is the administrator password for the firewall (empty when not
    needed); then "stop", or the pipe being closed (panel closed or killed),
    shuts the server down cleanly, like Ctrl+C."""
    import _thread
    import signal
    from .reporting import JsonReporter
    # Shutdown goes through a simulated Ctrl+C (interrupt_main): it must work even
    # if whoever started the panel was ignoring Ctrl+C (background processes).
    signal.signal(signal.SIGINT, signal.default_int_handler)
    for stream in (sys.stdin, sys.stdout):
        stream.reconfigure(encoding="utf-8")     # the panel reads and writes UTF-8 (on Windows too)
    password = sys.stdin.readline().rstrip("\r\n") or None

    def watch():
        for line in sys.stdin:
            if line.strip() == "stop":
                break
        _thread.interrupt_main()
    threading.Thread(target=watch, daemon=True).start()
    return JsonReporter(), password


def _desktop(check: bool):
    """Control panel. Any error while opening it is reported (file and message
    box) instead of being lost: from the shortcut there is no terminal to show it."""
    import traceback
    from .config import PROJECT_DIR
    from .desktop import main as desktop_main, report_failure
    try:
        desktop_main(load_config(), check)
    except SystemExit:
        raise
    except BaseException:
        text = traceback.format_exc()
        if check:
            sys.exit(text)
        report_failure(PROJECT_DIR / "desktop-error.log", text)
        sys.exit(1)


def main(argv=None):
    # A Windows terminal may lack some characters (« », accented letters): a
    # character that cannot be shown becomes "?" instead of stopping the program.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = _parser().parse_args(argv)
    if args.cmd == "desktop":
        _desktop(args.check)
        return
    if args.cmd == "firewall-uninstall":
        from .system.firewall import uninstall_old
        sys.exit(None if uninstall_old() else "Rimozione non riuscita.")
    config = load_config()
    try:
        if args.cmd == "serve":
            from .bootstrap import build_controllers
            from .server import run
            reporter, password = _controlled() if args.controlled else (None, None)
            run(config, build_controllers(config), args.host, args.port, reporter, password)
        else:
            _user_command(args, config)
    except ControlError as e:
        sys.exit(e.message)


if __name__ == "__main__":
    main()
