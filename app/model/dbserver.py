"""MODEL — old MariaDB database, used only to move the users to SQLite.

Earlier versions kept the users in a private MariaDB instance (data_dir/mysql).
On the first start with SQLite, if that instance exists and the new database is
empty, it is started for a moment (as a process of the user, without network
ports, through a socket file), the users are read and it is shut down again.
The data_dir/mysql folder is not deleted: it can be removed by hand once
everything has been checked.

On a computer without MariaDB (for example Windows) there is nothing to migrate.
"""
import getpass
import hashlib
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

SOCKET_MAX_LEN = 100  # Unix sockets have a limit of ~107 characters
LEGACY_DB_NAME = "notes_app"


class EmbeddedDBError(RuntimeError):
    pass


def _find(*names):
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


class EmbeddedMariaDB:
    def __init__(self, data_dir: Path):
        self.base = data_dir / "mysql"
        self.datadir = self.base / "data"
        self.logfile = self.base / "mariadb.log"
        self.pidfile = self.base / "mariadb.pid"
        sock = self.base / "mysqld.sock"
        if len(str(sock)) > SOCKET_MAX_LEN:
            # Path too long for a socket: use the user's temporary folder.
            runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
            digest = hashlib.sha1(str(self.base).encode()).hexdigest()[:10]
            sock = runtime / f"notes-app-{digest}.sock"
        self.socket = sock
        self.user = getpass.getuser()
        self.proc = None

    def exists(self) -> bool:
        return (self.datadir / "mysql").is_dir()

    def _connect(self, **kwargs):
        import pymysql
        return pymysql.connect(unix_socket=str(self.socket), user=self.user, connect_timeout=2,
                               cursorclass=pymysql.cursors.DictCursor, **kwargs)

    def alive(self) -> bool:
        if not self.socket.exists():
            return False
        try:
            self._connect().close()
            return True
        except Exception:                                    # noqa: BLE001 — qualunque errore = spento
            return False

    def start(self, timeout=30):
        """Starts the server unless it is already running (if it was, it is left as it is)."""
        if self.alive():
            return
        server = _find("mariadbd", "mysqld")
        if not server:
            raise EmbeddedDBError("MariaDB non è installato: non si possono leggere i vecchi utenti.")
        if self.socket.exists():
            self.socket.unlink()  # socket left over from an unclean shutdown
        self.proc = subprocess.Popen(
            [server, "--no-defaults", f"--datadir={self.datadir}", f"--socket={self.socket}",
             "--skip-networking", f"--pid-file={self.pidfile}", f"--log-error={self.logfile}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise EmbeddedDBError(f"MariaDB non si è avviato, vedi {self.logfile}")
            if self.alive():
                return
            time.sleep(0.3)
        self.stop()
        raise EmbeddedDBError(f"MariaDB non risponde dopo {timeout} s, vedi {self.logfile}")

    def stop(self, timeout=30):
        """Clean shutdown, only if this process started it."""
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def read_users(self) -> list[dict]:
        self.start()
        try:
            conn = self._connect(database=LEGACY_DB_NAME)
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, username, password_hash, created_at, last_login, "
                                "failed_attempts, locked_until FROM users ORDER BY id")
                    return list(cur.fetchall())
            finally:
                conn.close()
        finally:
            self.stop()


def migrate_legacy_users(store, data_dir: Path) -> int | None:
    """Moves the users of the old MariaDB database to SQLite, once only.
    Returns how many users were copied, or None if there was nothing to do."""
    legacy = EmbeddedMariaDB(data_dir)
    if not legacy.exists() or store.count_users() > 0 or store.migrated():
        return None
    return store.import_users(legacy.read_users(), source=str(legacy.base))
