"""VIEW — web routes, grouped by area. Each receives the request, passes it to
the controller and returns its answer (HTML page or JSON).

  pages.py    HTTPS certificate, login, sign-up, the app page
  library.py  document list, search, trash, layout previews
  account.py  profile photo, password change, account deletion
  editor.py   editor operations, notifications, images, backgrounds
"""
from . import account, editor, library, pages


def register_all(app):
    for module in (pages, library, account, editor):
        module.register(app)
