"""MODEL — storage of the users in an SQLite database.

This module only reads and writes rows of the `users` table: the rules (when
to lock an account, which passwords are valid, who may sign up) live in the
controller (control/auth.py).

The database is a single file (data_dir/tapbook.db) created automatically on
first start: no server to run, no network port, nothing to install.
Protections:
  * file readable and writable only by its owner (mode 600, folder 700);
  * every query uses parameters (?): no SQL injection;
  * secure_delete: deleted data (e.g. the hash of a deleted user) is
    overwritten, it does not stay readable in the file;
  * trusted_schema off and extensions cannot be loaded;
  * short writes in transactions (WAL), waiting if the file is busy:
    correct even with many parallel requests.
"""
import datetime as dt
import os
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT    NOT NULL UNIQUE COLLATE BINARY CHECK (length(username) BETWEEN 1 AND 32),
    password_hash   TEXT    NOT NULL CHECK (length(password_hash) <= 255),
    created_at      TEXT    NOT NULL,
    last_login      TEXT,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"     # local time, sortable as text
BUSY_TIMEOUT = 10                     # seconds to wait if the file is busy with another write
DB_FILE = "tapbook.db"


def _now(minutes: float = 0) -> str:
    return (dt.datetime.now() + dt.timedelta(minutes=minutes)).strftime(TIME_FORMAT)


def _when(value):
    return dt.datetime.strptime(value, TIME_FORMAT) if value else None


def _user(row, with_lock=False):
    if row is None:
        return None
    user = dict(row)
    for key in ("created_at", "last_login"):
        if key in user:
            user[key] = _when(user[key])
    if with_lock:
        # Lock still active: comparing texts in the same (sortable) format.
        user["locked"] = int(bool(user["locked_until"]) and user["locked_until"] > _now())
        user["locked_until"] = _when(user["locked_until"])
    return user


class UserStore:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / DB_FILE

    # --- connection ------------------------------------------------------------
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA trusted_schema = OFF")
        conn.execute("PRAGMA secure_delete = ON")
        return conn

    # Every query uses parameters (?): no SQL injection.
    def _query(self, sql, args=(), one=False):
        conn = self.connect()
        try:
            cur = conn.execute(sql, args)
            return cur.fetchone() if one else cur.fetchall()
        finally:
            conn.close()

    def ensure_database(self) -> bool:
        """Uses the database if it exists, otherwise creates it with its tables.
        Returns True if it was created now."""
        created = not self.path.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if created:
            # The file is created with the right permissions from the start (there is
            # no moment when other users of the computer could read it).
            os.close(os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        conn = self.connect()
        try:
            conn.execute("PRAGMA journal_mode = WAL")      # parallel reads and writes
            conn.executescript(SCHEMA)
        finally:
            conn.close()
        for suffix in ("", "-wal", "-shm"):
            f = Path(str(self.path) + suffix)
            if f.exists():
                os.chmod(f, 0o600)
        return created

    # --- reading ---------------------------------------------------------------
    def get_user(self, username):
        """User with the computed field `locked` (lock still active)."""
        return _user(self._query("SELECT * FROM users WHERE username = ?", (username,), one=True),
                     with_lock=True)

    def get_user_by_id(self, user_id):
        return _user(self._query("SELECT id, username, password_hash, created_at, last_login "
                                 "FROM users WHERE id = ?", (user_id,), one=True))

    def count_users(self) -> int:
        return self._query("SELECT COUNT(*) AS n FROM users", one=True)["n"]

    def list_users(self):
        return [_user(r) for r in self._query(
            "SELECT id, username, created_at, last_login FROM users ORDER BY username")]

    # --- writing ---------------------------------------------------------------
    def create_user(self, username, password_hash) -> bool:
        """Creates the user. False if the name is already taken (even with two
        simultaneous sign-ups: the UNIQUE constraint guarantees it)."""
        try:
            self._query("INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                        (username, password_hash, _now()))
        except sqlite3.IntegrityError:
            return False
        return True

    def set_password(self, username, password_hash):
        self._query("UPDATE users SET password_hash = ?, failed_attempts = 0, locked_until = NULL "
                    "WHERE username = ?", (password_hash, username))

    def delete_user(self, username):
        self._query("DELETE FROM users WHERE username = ?", (username,))
        # With secure_delete the row is overwritten in the file; the WAL log, however,
        # keeps the previous page until it is checkpointed: do it right away.
        self._query("PRAGMA wal_checkpoint(TRUNCATE)")

    def record_failure(self, user_id, lock_after: int, lock_minutes: int):
        """Counts a failed attempt and, once the threshold chosen by the controller is
        reached, sets the lock; after an expired lock the count starts again.
        A single UPDATE: correct even with simultaneous requests. In SQLite every
        SET expression sees the old values, so the new count is computed once
        (CASE) and reused to decide the lock."""
        now = _now()
        expired = "(locked_until IS NOT NULL AND locked_until <= :now)"
        count = f"(CASE WHEN {expired} THEN 1 ELSE failed_attempts + 1 END)"
        self._query(
            f"UPDATE users SET failed_attempts = {count}, "
            f"locked_until = CASE WHEN {count} >= :after THEN :until "
            f"                    WHEN {expired} THEN NULL ELSE locked_until END "
            "WHERE id = :id",
            {"now": now, "after": lock_after, "until": _now(lock_minutes), "id": user_id})

    def record_success(self, user_id):
        self._query("UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login = ? "
                    "WHERE id = ?", (_now(), user_id))

    # --- migration from the old MariaDB database -----------------------------------
    def migrated(self) -> bool:
        return self._query("SELECT 1 FROM meta WHERE key = 'migrated_from'", one=True) is not None

    def import_users(self, rows, source: str) -> int:
        """Copies the users read from the old database (same id, name, hash and dates)
        in a single transaction, once only. Returns how many were copied."""
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM meta WHERE key = 'migrated_from'").fetchone():
                conn.execute("ROLLBACK")
                return 0
            fmt = lambda v: v.strftime(TIME_FORMAT) if isinstance(v, dt.datetime) else v
            for r in rows:
                conn.execute(
                    "INSERT INTO users (id, username, password_hash, created_at, last_login, "
                    "failed_attempts, locked_until) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (r["id"], r["username"], r["password_hash"], fmt(r["created_at"]) or _now(),
                     fmt(r["last_login"]), r["failed_attempts"] or 0, fmt(r["locked_until"])))
            conn.execute("INSERT INTO meta (key, value) VALUES ('migrated_from', ?)", (source,))
            conn.execute("COMMIT")
            return len(rows)
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
