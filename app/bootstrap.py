"""Builds the application: this is where the three MVC layers are wired together.

It prepares the data folders, creates the models (user database, document
folders) and the controllers that use them. The command line (__main__.py)
only needs AuthController; the server (server.py) also uses the others and
the web view.
"""
import os
from dataclasses import dataclass

from .config import Config
from .control.account import AccountController
from .control.auth import AuthController
from .control.diagnostics import DiagnosticsController
from .control.editing import EditController
from .control.library import LibraryController
from .control.navigation import NavigationController
from .model.client_log import ClientLog
from .model.dbserver import EmbeddedDBError, migrate_legacy_users
from .model.user_store import UserStore


@dataclass
class Controllers:
    auth: AuthController
    library: LibraryController
    editing: EditController
    navigation: NavigationController
    account: AccountController
    diagnostics: DiagnosticsController


def prepare_storage(config: Config) -> UserStore:
    """Data folders and user database (created if missing). Internal data
    (session key, database, certificates, page cache) is readable only by
    the owner of the computer."""
    config.data_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(config.data_dir, 0o700)
    config.notes_root.mkdir(parents=True, exist_ok=True)
    store = UserStore(config.data_dir)
    if store.ensure_database():
        print(f"Database degli utenti creato: {store.path}")
    try:
        copied = migrate_legacy_users(store, config.data_dir)
    except EmbeddedDBError as e:
        print(f"ATTENZIONE: utenti del vecchio database MariaDB non copiati ({e}).")
    else:
        if copied is not None:
            print(f"Copiati {copied} utenti dal vecchio database MariaDB (la cartella "
                  f"{config.data_dir / 'mysql'} non serve più e si può eliminare).")
    return store


def build_auth(config: Config) -> AuthController:
    return AuthController(prepare_storage(config), config.notes_root, config.allow_registration)


def build_controllers(config: Config) -> Controllers:
    auth = build_auth(config)
    library = LibraryController(config.notes_root)
    editing = EditController(library, config.data_dir / "pagecache", config.edit_idle_minutes)
    navigation = NavigationController(library, editing)
    account = AccountController(auth, library, editing, config.notes_root)
    diagnostics = DiagnosticsController(ClientLog(config.data_dir))
    return Controllers(auth, library, editing, navigation, account, diagnostics)
