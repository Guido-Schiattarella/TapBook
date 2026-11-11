"""TapBook Sync: keeps a folder of this computer aligned with the user's folder
on a TapBook Server (on a VPS, or on another computer of the home network).

The app is still used from the browser; TapBook Sync only synchronises files.
You work on the folder as usual (copy, move, rename, delete, edit a PDF with
another program): the background service tells the server, which does the same.
What changes on the server (notes written on the iPad, new documents, deleted
ones) arrives on this computer the same way. The server never reaches this
computer: it is always the service that asks and acts.

  settings.py  where the settings, the device token and the state are kept
  api.py       the requests to the server (HTTPS, certificate, uploads in pieces)
  engine.py    the comparison computer ↔ server and the operations that align them
  service.py   the background service (always running) and its automatic start
  window.py    the window: server, account, folder, state, pause

Only the Python standard library is used (and Tk for the window).

    python -m app.syncclient            the window
    python -m app.syncclient service    the background service
    python -m app.syncclient status     the state, in the terminal
"""
