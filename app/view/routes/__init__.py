"""VIEW — web routes, grouped by area. Each receives the request, passes it to
the controller and returns its answer (HTML page or JSON).

  pages.py    HTTPS certificate, login, sign-up, the app page
  library.py  document list, search, trash, layout previews
  account.py  profile photo, password change, account deletion
  editor.py   editor operations, notifications, images, backgrounds
  diagnostics.py  errors of the interface reported by the browser
"""
from . import account, diagnostics, editor, library, pages


def register_all(app):
    for module in (pages, library, account, editor, diagnostics):
        module.register(app)
