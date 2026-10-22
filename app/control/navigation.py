"""CONTROL — navigation: decides which view the interface must show.

The view asks to open a path; the controller answers with the data and the
name of the view: "library" (document list) for a folder, "editor" for a PDF.
The view decides nothing: it switches to the view it is told.
"""
from .editing import EditController
from .errors import InvalidInput
from .library import LibraryController


class NavigationController:
    def __init__(self, library: LibraryController, editing: EditController):
        self.library = library
        self.editing = editing

    def library_view(self, username: str, listing) -> dict:
        path, entries = listing
        return {"view": "library", "path": path, "entries": entries,
                "newDocument": self.library.new_document_defaults(),
                "shell": self.library.shell(username)}

    def editor_view(self, username: str, rel: str, page=None, device=None) -> dict:
        result = {"view": "editor", **self.editing.open(username, rel, device)}
        result["color"] = self.library.document_color(username, result["path"])
        # Opened from a search result: the view goes to the matching page.
        if isinstance(page, int) and not isinstance(page, bool) and 0 <= page < len(result["pages"]):
            result["startPage"] = page
        return result

    def open(self, username: str, rel: str, page=None, device=None) -> dict:
        if self.library.kind(username, rel) == "dir":
            return self.library_view(username, self.library.list_folder(username, rel))
        return self.editor_view(username, rel, page, device)

    def search_view(self, username: str, query) -> dict:
        return {"view": "search", **self.library.search(username, query), "shell": self.library.shell(username)}

    def trash_view(self, username: str, message: str | None = None) -> dict:
        return {"view": "trash", "entries": self.library.trash_list(username), "message": message,
                "shell": self.library.shell(username)}

    def trash_restore(self, username: str, entry) -> dict:
        rel = self.library.trash_restore(username, entry)
        where = rel.rpartition("/")[0]
        return self.trash_view(username, f"«{rel.rpartition('/')[2]}» ripristinato in "
                                         f"{'Documenti/' + where if where else 'Documenti'}.")

    def trash_delete(self, username: str, entry) -> dict:
        self.library.trash_delete(username, entry)
        return self.trash_view(username, "Eliminato definitivamente.")

    def trash_empty(self, username: str) -> dict:
        self.library.trash_empty(username)
        return self.trash_view(username, "Cestino svuotato.")

    def create_document(self, username: str, rel: str, name, layout=None, color=None) -> dict:
        """New document (name, colour, layout of the first page): opens right away in the editor."""
        return self.editor_view(username, self.library.create_document(username, rel, name, layout, color))

    def _not_open(self, username: str, rel: str):
        if self.editing.is_open(username, rel):
            raise InvalidInput("Il documento è aperto in modifica su un dispositivo: chiudilo prima")

    def rename(self, username: str, rel: str, name) -> dict:
        self._not_open(username, rel)
        return self.library_view(username, self.library.rename(username, rel, name))

    def delete(self, username: str, rel: str) -> dict:
        self._not_open(username, rel)
        return self.library_view(username, self.library.delete(username, rel))

    def leave_editor(self, username: str, session_id: str) -> dict:
        """Leaving the editor: save and go back to the list of its folder."""
        folder = self.editing.close(username, session_id)
        return self.library_view(username, self.library.list_folder(username, folder))
