"""CONTROL — authentication and user profiles.

Business rules for login and sign-up. It uses the model (UserStore for the
database, UserFolder for the folders) and knows nothing about HTTP: the view
passes username, password and IP address and gets back a user or an AuthError.
"""
import hashlib
import hmac
import threading
import time
from pathlib import Path

from ..model.filesystem import UserFolder
from ..model.user_store import UserStore
from ..security import DUMMY_HASH, MAX_PASSWORD, hash_password, password_problem, valid_username, verify_password
from .errors import AuthError, InvalidInput

LOCK_AFTER_FAILURES = 5         # wrong attempts before the account is locked
LOCK_MINUTES = 5
LOGIN_ATTEMPTS_PER_IP = (10, 300)       # 10 attempts every 5 minutes
REGISTRATIONS_PER_IP = (5, 3600)        # 5 account all'ora
REGISTER_ATTEMPTS_PER_IP = (30, 3600)   # 30 sign-up attempts per hour (failed ones included)

INVALID_USERNAME = ("Nome utente non valido: 3-32 caratteri tra lettere minuscole, "
                    "numeri, '_' e '-', iniziando con una lettera o un numero.")


class Throttle:
    """Counts events per key (IP address or username) within a time window,
    in memory."""
    MAX_KEYS = 10000            # beyond this, keys without recent events are dropped

    def __init__(self, max_events: int, window: int):
        self.max_events, self.window = max_events, window
        self.events: dict[str, list[float]] = {}
        self.lock = threading.Lock()

    def _recent(self, key: str, now: float) -> list:
        recent = [t for t in self.events.get(key, []) if now - t < self.window]
        if recent:
            self.events[key] = recent
        else:
            self.events.pop(key, None)
        return recent

    def _prune(self, now: float):
        if len(self.events) > self.MAX_KEYS:
            for key in list(self.events):
                self._recent(key, now)

    def blocked(self, key: str) -> bool:
        with self.lock:
            return len(self._recent(key, time.time())) >= self.max_events

    def record(self, key: str):
        with self.lock:
            now = time.time()
            self._prune(now)
            self.events.setdefault(key, []).append(now)

    def attempt(self, key: str) -> bool:
        """Checks and counts in a single step: False if the limit is already
        reached. With parallel requests none gets past the limit (checking and
        counting at two different moments would allow it)."""
        with self.lock:
            now = time.time()
            if len(self._recent(key, now)) >= self.max_events:
                return False
            self._prune(now)
            self.events.setdefault(key, []).append(now)
            return True

    def forget(self, key: str):
        """Removes the last counted event (the attempt succeeded)."""
        with self.lock:
            if self.events.get(key):
                self.events[key].pop()


class UnknownUserFailures:
    """Failed attempts on usernames that do not exist, counted with the same
    rules the database uses for real accounts (UserStore.record_failure):
    after LOCK_AFTER_FAILURES errors the name is locked for LOCK_MINUTES
    minutes. This way the "account locked" message and its timing do not
    reveal which names are registered."""
    MAX_NAMES = 10000

    def __init__(self):
        self.names: dict[str, list] = {}       # nome -> [errori, bloccato fino a]
        self.lock = threading.Lock()

    def locked(self, name: str) -> bool:
        with self.lock:
            entry = self.names.get(name)
            return bool(entry and entry[1] and entry[1] > time.time())

    def record(self, name: str):
        with self.lock:
            now = time.time()
            entry = self.names.pop(name, None) or [0, None]
            if entry[1] and entry[1] <= now:   # lock expired: start counting again
                entry = [0, None]
            entry[0] += 1
            if entry[0] >= LOCK_AFTER_FAILURES:
                entry[1] = now + LOCK_MINUTES * 60
            self.names[name] = entry
            while len(self.names) > self.MAX_NAMES:      # forget the oldest ones
                del self.names[next(iter(self.names))]


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def session_fingerprint(password_hash: str) -> str:
    """Password fingerprint stored in the session: when the password changes,
    sessions opened earlier (for example on another iPad) are no longer valid."""
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:24]


def _session(user) -> dict:
    return {"id": user["id"], "username": user["username"],
            "fp": session_fingerprint(user["password_hash"])}


class AuthController:
    def __init__(self, store: UserStore, notes_root: Path, allow_registration: bool):
        self.store = store
        self.notes_root = notes_root
        self.allow_registration = allow_registration
        self.login_throttle = Throttle(*LOGIN_ATTEMPTS_PER_IP)
        self.register_throttle = Throttle(*REGISTRATIONS_PER_IP)
        self.register_attempts = Throttle(*REGISTER_ATTEMPTS_PER_IP)
        # Errors on names that do not exist lock just like a real account, so the
        # "account locked" message does not reveal which names are registered.
        self.unknown_failures = UnknownUserFailures()

    # --- state ----------------------------------------------------------------
    def needs_first_user(self) -> bool:
        return self.store.count_users() == 0

    def registration_open(self) -> bool:
        # The first account can always be created, even with sign-up turned off.
        return self.allow_registration or self.needs_first_user()

    def session_user(self, user_id, username, fingerprint):
        """The session user, only if it still exists with the same name and the
        password has not changed since login."""
        if not user_id or not isinstance(fingerprint, str):
            return None
        user = self.store.get_user_by_id(user_id)
        if not user or user["username"] != username:
            return None
        if not hmac.compare_digest(fingerprint, session_fingerprint(user["password_hash"])):
            return None
        return {k: user[k] for k in ("id", "username", "created_at", "last_login")}

    # --- login ------------------------------------------------------------------
    def login(self, username: str, password: str, ip: str) -> dict:
        username = normalize_username(username)[:64]
        # The attempt is counted right away (and removed if it succeeds): even many
        # parallel requests cannot go past the per-address limit.
        if not self.login_throttle.attempt(ip):
            raise AuthError("Troppi tentativi. Riprova tra qualche minuto.")
        user = self.store.get_user(username) if valid_username(username) else None
        if (user["locked"] if user else self.unknown_failures.locked(username)):
            raise AuthError("Account temporaneamente bloccato per troppi tentativi.")
        if not isinstance(password, str) or len(password) > MAX_PASSWORD:
            password = ""           # no valid password is that long: it is still compared (same timing)
        if user and verify_password(password, user["password_hash"]):
            self.store.record_success(user["id"])
            self.login_throttle.forget(ip)
            return _session(user)
        if user:
            self.store.record_failure(user["id"], LOCK_AFTER_FAILURES, LOCK_MINUTES)
        else:
            verify_password(password, DUMMY_HASH)  # same response time: does not reveal who exists
            self.unknown_failures.record(username)
        raise AuthError("Nome utente o password errati.")

    # --- sign-up ----------------------------------------------------------------
    def register(self, username: str, password: str, confirm: str, ip: str) -> dict:
        """Creates the user in the database and its folder. Returns the user."""
        if not self.registration_open():
            raise AuthError("La registrazione non è attiva.")
        username = normalize_username(username)
        if self.register_throttle.blocked(ip) or not self.register_attempts.attempt(ip):
            raise InvalidInput("Troppe registrazioni da questo dispositivo. Riprova più tardi.")
        if not valid_username(username):
            raise InvalidInput(INVALID_USERNAME)
        if password != confirm:
            raise InvalidInput("Le due password non coincidono.")
        if problem := password_problem(password, username):
            raise InvalidInput(problem)
        if not UserFolder.is_free(self.notes_root, username):
            # A non-empty folder with that name already exists (e.g. of a deleted
            # user): it is not handed over to whoever signs up now.
            raise InvalidInput("Nome utente non disponibile.")
        # The slot among the allowed accounts is reserved before creating the user:
        # even parallel sign-ups cannot go past the limit.
        if not self.register_throttle.attempt(ip):
            raise InvalidInput("Troppe registrazioni da questo dispositivo. Riprova più tardi.")
        if not self.store.create_user(username, hash_password(password)):
            self.register_throttle.forget(ip)
            raise InvalidInput("Nome utente già in uso.")
        UserFolder(self.notes_root, username)  # create the personal folder
        return _session(self.store.get_user(username))

    # --- account from the web -------------------------------------------------------
    def check_password(self, username: str, password, ip: str) -> dict:
        """Confirms the current password for account operations. Errors count as
        failed login attempts (same lock as the login)."""
        if not self.login_throttle.attempt(ip):
            raise InvalidInput("Troppi tentativi. Riprova tra qualche minuto.")
        user = self.store.get_user(username)
        if not user:
            raise InvalidInput("Utente inesistente.")
        if user["locked"]:
            raise InvalidInput("Account temporaneamente bloccato per troppi tentativi: riprova tra qualche minuto.")
        if (not isinstance(password, str) or len(password) > MAX_PASSWORD
                or not verify_password(password, user["password_hash"])):
            self.store.record_failure(user["id"], LOCK_AFTER_FAILURES, LOCK_MINUTES)
            raise InvalidInput("Password attuale errata.")
        self.login_throttle.forget(ip)
        return user

    def change_own_password(self, username: str, current, new, confirm, ip: str) -> str:
        """Password change from the web. Returns the new fingerprint for the session
        of whoever changed it (all other sessions are closed)."""
        self.check_password(username, current, ip)
        if not isinstance(new, str) or new != confirm:
            raise InvalidInput("Le due nuove password non coincidono.")
        if problem := password_problem(new, username):
            raise InvalidInput(problem)
        if new == current:
            raise InvalidInput("La nuova password deve essere diversa da quella attuale.")
        self.store.set_password(username, hash_password(new))
        return session_fingerprint(self.store.get_user(username)["password_hash"])

    # --- administration from the terminal ---------------------------------------------
    def create_user(self, username: str, password: str) -> Path:
        """Creation from the terminal: like sign-up, but the administrator may
        reassign an existing folder."""
        username = normalize_username(username)
        if not valid_username(username):
            raise InvalidInput(INVALID_USERNAME)
        if problem := password_problem(password, username):
            raise InvalidInput(problem)
        if not self.store.create_user(username, hash_password(password)):
            raise InvalidInput("Utente già esistente.")
        return UserFolder(self.notes_root, username).root

    def change_password(self, username: str, password: str):
        if not self.store.get_user(username):
            raise InvalidInput("Utente inesistente.")
        if problem := password_problem(password, username):
            raise InvalidInput(problem)
        self.store.set_password(username, hash_password(password))

    def delete_user(self, username: str):
        """Deletes the profile; the documents folder stays on disk."""
        if not self.store.get_user(username):
            raise InvalidInput("Utente inesistente.")
        self.store.delete_user(username)

    def list_users(self):
        return self.store.list_users()
