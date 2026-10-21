"""CONTROL — account management from the web: profile photo, password change,
account deletion.

Every sensitive operation asks for the current password (with the same
anti-guessing lock as the login). Deleting an account never destroys the
documents: the folder is moved to <notes_root>/.account-eliminati/ and can be
recovered from the computer.
"""
from pathlib import Path

from ..model.filesystem import UserFolder
from ..model.pictures import InvalidPicture, prepare_avatar
from .errors import InvalidInput, NotFound

MAX_AVATAR_BYTES = 20 * 1024 * 1024


def _epoch(value):
    return int(value.timestamp()) if value else None


class AccountController:
    def __init__(self, auth, library, editing, notes_root: Path):
        self.auth = auth
        self.library = library
        self.editing = editing
        self.notes_root = notes_root

    def account_view(self, user: dict, message: str | None = None) -> dict:
        """Data for the account page. `user` is the session user."""
        folder = self.library.folder(user["username"])
        return {"view": "account", "user": self.library.user_summary(user["username"]),
                "created": _epoch(user.get("created_at")), "lastLogin": _epoch(user.get("last_login")),
                "stats": folder.stats(), "message": message, "shell": self.library.shell(user["username"])}

    # --- profile photo ------------------------------------------------------------------
    def set_avatar(self, user: dict, data: bytes) -> dict:
        if not data or len(data) > MAX_AVATAR_BYTES:
            raise InvalidInput("Immagine troppo grande o vuota")
        try:
            picture = prepare_avatar(data)   # the model crops and resizes it
        except InvalidPicture as e:
            raise InvalidInput(str(e))
        self.library.folder(user["username"]).save_avatar(picture)
        return self.account_view(user, "Foto del profilo aggiornata.")

    def remove_avatar(self, user: dict) -> dict:
        self.library.folder(user["username"]).remove_avatar()
        return self.account_view(user, "Foto del profilo rimossa.")

    def avatar_path(self, username: str) -> Path:
        path = self.library.folder(username).avatar_path()
        if path is None:
            raise NotFound("Nessuna foto del profilo")
        return path

    # --- password and deletion --------------------------------------------------------------
    def change_password(self, user: dict, current, new, confirm, ip: str):
        """Returns (view, new password fingerprint for the session)."""
        fingerprint = self.auth.change_own_password(user["username"], current, new, confirm, ip)
        return self.account_view(user, "Password cambiata. Gli altri dispositivi dovranno rifare l'accesso."), fingerprint

    def delete_account(self, user: dict, password, confirm_name, ip: str):
        """Deletes the account: asks for the password and the username typed in full."""
        username = user["username"]
        if not isinstance(confirm_name, str) or confirm_name.strip().lower() != username:
            raise InvalidInput("Per confermare scrivi esattamente il tuo nome utente.")
        self.auth.check_password(username, password, ip)
        self.editing.close_user(username)      # open documents: saved and closed
        self.auth.delete_user(username)
        UserFolder.archive_account(self.notes_root, username)
