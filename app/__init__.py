"""TapBook: multi-user PDF notes, edited from an iPad through the browser.

Layout:
  __main__.py   command line (python -m app …)
  bootstrap.py  builds the app: models and controllers wired together
  server.py     web server (HTTPS, firewall, orderly shutdown)
  config.py     configuration (config.ini and NOTES_* environment variables)
  security.py   passwords, safe names and paths
  model/        MODEL: users (SQLite), folders, PDFs
  control/      CONTROL: business logic
  view/         VIEW: web pages and API, the interface running in the iPad browser
  desktop/      control panel (a window to start and stop the server)
  system/       operating-system specific parts: certificates, network, firewall,
                update check
"""

# App version: bump it for every new GitHub Release (tag "v" + version,
# e.g. v1.1.0). The control panel compares it with the latest Release.
__version__ = "0.1.1"
# GitHub repository of the official Releases, "owner/repository". Empty: the
# control panel does not check for updates. Whoever installs the app can change it
# or turn the check off in config.ini (update_repository, update_check).
__repository__ = "Guido-Schiattarella/TapBook"
