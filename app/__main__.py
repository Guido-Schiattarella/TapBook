"""TapBook command line (same on Linux and Windows). Once installed, the
`tapbook` command is the same as "python -m app".

    tapbook desktop                     control panel (window to start and stop the server)
    tapbook serve [--host H] [--port P] runs the server in the terminal
    tapbook status                      version, settings in use, users, service, reachability
    tapbook user add <name>             creates a profile (asks for the password)
    tapbook user passwd <name>          changes a password
    tapbook user del <name>             deletes a profile (its folder stays on disk)
    tapbook user list                   lists the profiles
    tapbook device list [name]          computers paired with TapBook Sync
    tapbook device revoke <id>          unpairs a computer (it must log in again)
    tapbook config show                 every setting, its value and where it comes from
    tapbook config export               a complete config.ini to copy to another server
    tapbook service enable | disable | start | stop | restart
                                        (Linux) server as a background service
    tapbook logs [-f] [-n N]            messages of the background service
    tapbook init-db                     creates the user database if missing
                                        (every command does it anyway)
    tapbook firewall-uninstall          (Linux) removes the firewall helper installed
                                        by earlier versions and its sudo rule

add-user, passwd, del-user and list-users still work as in earlier versions.
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
    # Started by systemd (tapbook service enable): no terminal, no panel.
    serve.add_argument("--service", action="store_true", help=argparse.SUPPRESS)
    for name in ("add-user", "passwd", "del-user"):           # names of earlier versions
        sub.add_parser(name).add_argument("username")
    sub.add_parser("list-users")
    user = sub.add_parser("user", help="profili: add, passwd, del, list")
    user_sub = user.add_subparsers(dest="user_cmd", required=True)
    for name in ("add", "passwd", "del"):
        user_sub.add_parser(name).add_argument("username")
    user_sub.add_parser("list")
    device = sub.add_parser("device", help="computer collegati con TapBook Sync: list, revoke")
    device_sub = device.add_subparsers(dest="device_cmd", required=True)
    device_sub.add_parser("list").add_argument("username", nargs="?")
    device_sub.add_parser("revoke").add_argument("device_id", type=int)
    config = sub.add_parser("config", help="impostazioni: show, export")
    config.add_argument("action", choices=("show", "export"))
    service = sub.add_parser("service", help="servizio in background (Linux)")
    service.add_argument("action", choices=("enable", "disable", "start", "stop", "restart"))
    logs = sub.add_parser("logs", help="messaggi del servizio")
    logs.add_argument("-f", "--follow", action="store_true")
    logs.add_argument("-n", "--lines", type=int, default=100)
    sub.add_parser("status")
    sub.add_parser("init-db")
    sub.add_parser("firewall-uninstall")
    return parser


# "tapbook user add" and the older "tapbook add-user" do the same thing.
USER_COMMANDS = {"add": "add-user", "passwd": "passwd", "del": "del-user", "list": "list-users"}


def _user_command(args, config):
    from .bootstrap import build_auth
    if args.cmd == "user":
        args.cmd = USER_COMMANDS[args.user_cmd]
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
        users = auth.list_users()
        for u in users:
            print(f"{u['username']:<32} creato {u['created_at']}  ultimo accesso {u['last_login'] or '-'}")
        if not users:
            print("Nessun utente. Crealo con:  tapbook user add <nome>")


def _device_command(args, config):
    from .bootstrap import build_auth
    store = build_auth(config).store
    if args.device_cmd == "list":
        devices = store.list_devices(args.username)
        for d in devices:
            print(f"{d['id']:>4}  {d['username']:<20} {d['name']:<30} collegato {d['created_at']}"
                  f"  ultimo contatto {d['last_seen'] or '-'}")
        if not devices:
            print("Nessun computer collegato con TapBook Sync.")
    elif store.delete_device(args.device_id):
        print("Computer scollegato: TapBook Sync dovrà rifare l'accesso.")
    else:
        sys.exit("Nessun dispositivo con questo numero (vedi  tapbook device list).")


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
    if args.cmd == "config":
        from .cli import config_export, config_show
        print(config_show() if args.action == "show" else config_export(), end="")
        return
    if args.cmd in ("service", "logs"):
        from .system import service
        try:
            if args.cmd == "logs":
                sys.exit(service.logs(args.lines, args.follow))
            elif args.action == "enable":
                service.enable()
                print("Servizio attivo: TapBook Server parte ora e a ogni accensione. Stato:  tapbook status")
            elif args.action == "disable":
                service.disable()
                print("Servizio fermato e rimosso.")
            else:
                service.control(args.action)
        except service.ServiceError as e:
            sys.exit(str(e))
        return
    config = load_config()
    try:
        if args.cmd == "serve":
            from .bootstrap import build_controllers
            from .server import run
            reporter, password = _controlled() if args.controlled else (None, None)
            run(config, build_controllers(config), args.host, args.port, reporter, password, args.service)
        elif args.cmd == "device":
            _device_command(args, config)
        elif args.cmd == "status":
            from .cli import status
            print(status(config), end="")
        else:
            _user_command(args, config)
    except ControlError as e:
        sys.exit(e.message)


if __name__ == "__main__":
    main()
