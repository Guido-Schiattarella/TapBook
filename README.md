<p align="center">
  <img src="app/view/static/img/logo-128.png" alt="TapBook logo" width="96">
</p>

<h1 align="center">TapBook</h1>

<p align="center">
  Write on your PDFs with the Apple Pencil, from the iPad browser.<br>
  Every stroke is saved straight into the PDF on your computer.
</p>

<p align="center">
  <a href="../../releases/latest">Download</a> ·
  <a href="#installation">Installation</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#license">License</a>
</p>

---

TapBook is a small multi-user server that runs on your Linux or Windows computer
(or on your own VPS) and serves a notes app to the iPad. You open it in
Safari, write on your PDFs with the Apple Pencil, and every change is saved
into the real PDF file on the server about one second after you stop writing.
There is no cloud, no account with anyone and no subscription: the documents are
ordinary PDF files in a folder.

It comes in two parts, chosen when installing:

- **TapBook Server**: the app itself, always used from the browser. On a computer
  of your home network, or on a VPS to reach it from anywhere.
- **TapBook Sync**: a small program for your computers. It keeps a folder of the
  computer aligned with your folder on the server, in both directions: you work
  on the files as usual and the changes travel by themselves.

> [!NOTE]
> The interface of the app (web pages and control panel) is in **Italian**. The
> code, comments, installers and this documentation are in English.

## Features

**Writing**
- Pen and highlighter in 6 colours: the highlighter keeps its own colour, pen,
  shapes and text share one. Thickness: three standard sizes (small,
  medium, large) or a custom one chosen with a slider from very thin (0.2 pt) to
  very thick (16 pt), remembered separately for pen, highlighter and shapes.
  Eraser in three sizes. The stroke follows the
  Pencil tip closely, with only light smoothing.
- Full Apple Pencil support with palm rejection: the Pencil writes and the finger
  scrolls. The hand resting on the screen (a touch as wide as a palm, or a finger
  arriving while the Pencil writes) neither scrolls nor zooms. All the Pencil's
  high-frequency samples are used, so strokes are smooth.
- Shape recognition: draw a line, circle, ellipse, triangle, square or rectangle
  freehand and it becomes a clean shape. Hold the pen still at the end of a stroke
  to do the same without switching tools.
- Lasso: select strokes, text boxes and images, then move, recolour, duplicate or
  delete them. Copy and paste (also with Cmd+C / Cmd+V, under the mouse): what
  you copied can be pasted on another page or in another document, and becomes
  the selection so it can be dragged right away. Pasting from the device's
  clipboard works too: a text becomes a text box, an image a picture. Right click
  (or hold a finger on the page) opens the menu with copy, cut, paste and delete.
- Text boxes typed from the keyboard, with adjustable font size. Tap a box in
  text mode to edit it again; the box can be moved, resized and deleted, and
  dragged onto another page (the same for photos).
- Photos from the iPad camera or library. Photos can be moved, resized and
  deleted, even after the document is reopened.
- Keyboard shortcuts (with a keyboard connected to the iPad): **P** pen,
  **H** highlighter, **E** eraser, **L** lasso, **F** shapes, **T** text,
  **Esc** to leave a text box, **Cmd+Z** / **Cmd+Shift+Z** to undo and redo,
  **Cmd+C** / **Cmd+X** / **Cmd+V** copy, cut and paste, **Page Up** / **Page Down**
  to turn the page.
- Pens with buttons: holding the side button, the pen becomes a hand that moves
  the sheet (the mouse wheel button does the same); the eraser end of the pen
  erases while it touches.
- Undo and redo for the whole session.
- Pinch to zoom from 0.5× to 10×, without redrawing the pages from scratch.
  One finger scrolls with the browser's own scrolling (as responsive as on any
  page); the zoom is TapBook's, and a second finger stops the scrolling, so it
  always zooms; the PDF pages, and the strokes while the sheet
  moves, are drawn in worker threads, so scrolling never waits for a drawing.
  With strong zoom a low-resolution copy of the whole page sits under the sharp
  part, so scrolling never shows holes.
- Gestures with one finger: a quick swipe sideways turns the page, two taps zoom
  in on that point (two taps again, or two taps with two fingers, go back to the
  page width).
- Page chooser with thumbnails (tap the page number in the toolbar, or the
  "Pagina 3 di 8" indicator) and a field to type the page number.
- Every document reopens at the page where you stopped, on any device.
- Closing never waits for the PDF to be written, and a document reopens in a
  fraction of a second even with thousands of strokes (the computer remembers
  the notes of every file it wrote or read, keyed by the file's content).
- Saving is incremental: only what changed since the last save is appended to
  the PDF; the file is rewritten compact on close, every 25 incremental saves
  and when pages change. Each annotation carries its own editable data.

**Documents**
- Folders, new notebooks with a pastel colour and a page layout. Layouts: blank,
  ruled, grid, dotted, and Cornell ruled or Cornell grid.
- Import any PDF from the iPad, then add, remove or change the layout of pages.
- Fast reopening: each device keeps the pages it has already downloaded, so a
  document opens without downloading it again. Only pages changed on the computer
  (by another program) are downloaded again; pages added, removed or moved with
  TapBook never need a download.
- Search across all your documents: names, folders and the text inside the PDFs
  (lecture notes, slides…). Capitals and accents do not matter.
- Trash with restore, so deleted items can be brought back.
- The same document can be open on several devices at once: changes appear on
  all of them.

**Accounts**
- Several people can use the same computer: each person has an account and a
  private folder.
- Accounts are created from the login page (the first one on first start) or, with
  sign-up closed, only from the server's terminal (`tapbook user add`).
- Profile photo, password change and account deletion from the web. Deleting an
  account does not delete the documents.

**On the computer**
- A control panel window to start and stop the server. It shows the address to
  open on the iPad, the whole configuration (with an export for another server)
  and tells you when a new version is available.
- Zero setup: the user database (SQLite), the HTTPS certificates and the
  configuration are created automatically.

**On a VPS**
- Without a screen the server installs as a background service that starts with
  the machine. Everything is managed with the `tapbook` command: accounts,
  state, configuration, logs, paired computers.
- Sign-up can be closed completely: accounts are then created only from the
  server's terminal.
- Your own certificate (for example Let's Encrypt, renewed without restarting),
  or a reverse proxy (Caddy, nginx) in front, or a VPN with no open ports.

**TapBook Sync**
- Copy, move, rename, delete or edit files in the folder on your computer: the
  server does the same. Notes written on the iPad, new and deleted documents
  arrive on the computer the same way, usually within a second.
- Moves and renames are recognised, even a whole folder renamed (one step on the
  server) or a file moved and changed at the same time: nothing is transferred again.
- Nothing is lost: a file changed on both sides is kept twice (`name (conflitto
  …)`), deleted files go to a trash on both sides, and a large deletion at once
  waits for your confirmation.
- Large files travel in pieces and an interrupted transfer resumes.
- The server never reaches your computer: it is always TapBook Sync that asks.

## Installation

Download the package for your system from the
**[latest release](../../releases/latest)**.

### Linux

1. Extract `TapBook-<version>-linux.tar.gz`.
2. Open a terminal in the extracted folder and run:
   ```bash
   bash install.sh
   ```
3. The installer asks:
   - what to install: **TapBook Server** or **TapBook Sync**;
   - if it is already installed: **update** it (settings untouched, no
     questions) or **install it from scratch** (all the questions again; the old
     settings are kept as a backup, documents and accounts stay where they are);
   - for a new server: whether anyone can sign up from the login page, or only
     you from the terminal (then it creates your account right away).
4. It then:
   - asks for the administrator password;
   - checks Python 3.10+, `venv` and Tk and installs whatever is missing with the
     distribution's package manager (it asks first);
   - installs the server in `~/.local/share/tapbook` (command `tapbook`) or
     TapBook Sync in `~/.local/share/tapbook-sync` (command `tapbook-sync`);
   - adds them to the applications menu. On a machine without a screen the
     server becomes a background service (see [TapBook on a VPS](#tapbook-on-a-vps)).

   A progress bar shows each step. The full log is saved in `install.log` in the
   installation folder.

**Supported distributions:** recent versions of Arch Linux and its derivatives
(Manjaro, EndeavourOS…), Debian 12+, Ubuntu 22.04+ and its derivatives (Linux Mint,
Pop!_OS…), Fedora and openSUSE Tumbleweed. `sudo` is required. On other
distributions, install Python 3.10+ with `venv` and Tk yourself, then run the
installer.

### Windows

1. Extract `TapBook-<version>-windows.zip`. Extract the whole archive; do not run
   the installer from inside the zip.
2. Right-click **`Install TapBook.cmd`** and choose **Run as administrator**.
3. It asks the same questions as on Linux (Server or Sync, update or from
   scratch, sign-up).
4. If Python 3.10+ is missing, the installer installs it with `winget` or with the
   official python.org installer, after checking its signature.
5. **TapBook Server** or **TapBook Sync** appears in the Start menu and on the
   desktop. The full log is saved in `install.log` in
   `%LOCALAPPDATA%\Programs\TapBook` (or `…\TapBook Sync`). For the server,
   `tapbook.cmd` in that folder is the `tapbook` command of the terminal.

It is made for Windows 10 and 11 (64-bit).

### Updating

Download the new package, close TapBook and run the installer again. Documents,
accounts and settings are kept. The control panel tells you when a new release
is out. It makes a single request to the GitHub API: no data is sent and nothing
is downloaded automatically.

### Uninstalling

- **Linux:** run `~/.local/share/tapbook/uninstall.sh` (server) or
  `~/.local/share/tapbook-sync/uninstall.sh` (TapBook Sync).
- **Windows:** go to *Settings → Apps → Installed apps → TapBook Server* (or
  *TapBook Sync*).

Your documents and the synchronised folder are never deleted. The internal data
(accounts, certificate) and the TapBook Sync settings are removed only if you
confirm.

## Getting started

1. Open **TapBook** on the computer and press **Avvia il server** (start the
   server).
   - If the firewall is active, Linux asks for the administrator password and
     Windows asks for a confirmation.
   - The window then shows the address to open on the iPad, for example
     `https://192.168.1.20:8000`.
2. On the iPad, connected to the same Wi-Fi network, open that address in Safari.
3. **First time only:**
   1. Safari warns about the certificate. Tap *Show Details → visit this website*.
   2. On the login page, tap **Installa il certificato** (install the certificate)
      and follow the steps.
   3. From then on the connection is trusted and encrypted.
4. Create your account. The first one is created right away; later ones from the
   *Registrati* (sign up) link. With sign-up closed, the accounts are created on
   the server with `tapbook user add <name>`.
5. Optional: tap *Share → Add to Home Screen* to open TapBook full screen, like an app.

Your documents are in the `Note` folder in your home folder:

| | Folder |
|---|---|
| Linux | `~/Note/<user>/` |
| Windows | `%USERPROFILE%\Note\<user>\` |

You can also add, copy or back up PDFs there directly from the computer.

### TapBook Sync

1. Install **TapBook Sync** on your computer and open it.
2. Press **Collega…** (connect) and enter the server address (the one you open in
   the browser), your username and password. The password is used once and
   never saved: the computer receives its own access key, which you can revoke
   from the server (`tapbook device revoke`).
   - If the server uses the certificate created by TapBook, TapBook Sync shows its
     fingerprint: compare it with the *Impronta HTTPS* line of `tapbook status`
     on the server, then confirm.
3. Choose the folder to synchronise (by default `TapBook` in your home folder).

If the folder already contains files, and the server too, the first
synchronisation merges them and never deletes anything: files only on one side
are copied to the other, identical files are left as they are, and a file with
the same name but different content on the two sides is kept twice (the
computer's copy is renamed `name (conflitto <computer> <date>)`). On Windows,
which does not tell capitals apart, two names differing only in capitals are
never mixed up: same content takes the server's name, a different one becomes a
conflict copy.

From then on TapBook Sync runs in the background and starts at every login;
the window only shows what it is doing and lets you pause it. Files whose names
are not allowed on every system (characters like `: * ? " < > |`, names longer
than 120 characters) and hidden files stay only on the computer and are listed
in the window. Files deleted on the server end up in `.tapbook-sync/cestino`
inside the folder for 30 days.

## How it works

```
 iPad (Safari)                                Computer
┌──────────────────────┐   HTTPS, local     ┌──────────────────────────────────┐
│ Web editor           │   network only     │ TapBook server (Python, Flask)   │
│ pdf.js renders pages │ ─────────────────▶ │ PyMuPDF writes strokes, text and │
│ Pencil → strokes     │ ◀───────────────── │ images into the PDF files        │
└──────────────────────┘                    │ SQLite: accounts                 │
                                            │ ~/Note/<user>/*.pdf: documents   │
                                            └──────────────────────────────────┘
```

**Rendering and saving**
- The iPad renders the pages with pdf.js and records the strokes.
- The pages without the notes (the "background") are downloaded once and kept
  on the device (browser Cache Storage, up to 1 GB, separate for each user and
  cleared when logging out). Every page has a fingerprint of its content: when
  a document is opened again, only the pages whose fingerprint is new are
  downloaded. The computer keeps a copy of these backgrounds in its data folder
  (`backgrounds`), deleted 30 days after the document was last opened.
- Each stroke is sent to the computer as soon as it is finished, so nothing is
  lost if Safari closes.
- About one second after the last change, the server writes the strokes, text
  boxes and images into the PDF with PyMuPDF. The document stays usable while the
  PDF is written: on Linux the writing happens in a separate process (stopped and
  replaced if it ever stops answering), on Windows inside the server.
- The annotations are kept editable inside the file. The PDF stays a normal PDF
  that any viewer can open, with your handwriting in it.

**Shared documents and conflicts**
- When the same document is open on several devices, the server merges their
  changes and sends each device the changes of the others. If a device changes
  something that another one has just deleted (for example it moves an image
  removed a moment earlier), the change is simply dropped: no error.
- If a PDF is changed on the computer while it is open on the iPad, TapBook
  notices it. One version wins and the other is kept in the trash, so nothing is
  overwritten silently.

**Synchronisation (TapBook Sync)**
- The service compares three lists: the folder now, the server now, and how the
  two were the last time they were aligned. This tells who changed what: changed
  only here → uploaded; only on the server → downloaded; deleted on one side and
  untouched on the other → deleted on the other side too.
- The operating system tells it when something changes in the folder (inotify on
  Linux, ReadDirectoryChangesW on Windows); where that is not possible it looks at
  the folder every 2 seconds (sizes and dates only). It also keeps a request open
  towards the server, which answers as soon as something changes there. It is
  always the computer that asks: the server never connects to it.
- The server keeps a numbered list of the changes of each folder and sends only
  the ones after the last the computer saw, not the whole list.
- Moves are recognised by the file's identity on disk (the inode, kept by a
  rename) and by its fingerprint. A file moved and changed at the same time is
  moved on the server and its new content uploaded; the server keeps the replaced
  version in its trash.
- Every change sent to the server names the version the computer knew (the
  SHA-256 of the file): if meanwhile the file changed on the server, the change is
  refused and both versions are kept.
- A document open in the editor is not deleted or moved by the synchronisation:
  it waits until the document is closed, as from the web.

**Code structure**
- The code follows the MVC pattern:
  - `app/model`: files, PDFs, users;
  - `app/control`: the logic;
  - `app/view`: the web pages and the API.
- More parts sit next to it:
  - `app/desktop`: the Tk control panel;
  - `app/system`: the code that is specific to each operating system
    (certificates, network, firewall, background service, update check);
  - `app/syncclient`: TapBook Sync, which uses only the Python standard library.

### Security

TapBook was first designed for a **home network**; for a server on the Internet
see [TapBook on a VPS](#tapbook-on-a-vps).

| Area | How it is protected |
|---|---|
| Connection | HTTPS, with a private certificate authority created on your computer. You install it once on each iPad. |
| Passwords | Stored with scrypt and never in clear text. Logins are rate-limited and failed attempts lock the account for a while. Parallel login floods cannot exhaust memory. |
| Requests | Sessions are signed; requests carry CSRF protection. |
| Files | Uploaded files are checked. Names and paths are sanitised (no path traversal, symlinks or Windows device names), so each user can only reach their own folder. |
| Firewall | No need to disable it or open ports by hand (see below). |
| Sign-up | Can be closed completely: no account, not even the first, can then be created from the web. |
| TapBook Sync | Each computer has its own random key (only its SHA-256 is stored on the server), revoked from the terminal and when the password changes. The server never connects to the computer, and the computer ignores any path from the server that would lead outside the synchronised folder. |
| Logs | Failed logins are written to the log with the address, for tools such as fail2ban. |

**How the firewall is handled**
- When the server starts, TapBook opens its port **only for the local subnet**
  and **only while the server is running**. It works with ufw, firewalld,
  nftables, iptables (and tools built on them) and Windows Defender Firewall.
- The rule is temporary and is removed when the server stops, even if it crashes
  or is killed.
- The administrator password is asked at every start and never stored. No
  `sudoers` rule or permanent service is installed.

> [!WARNING]
> TapBook has not been professionally audited. On the Internet use HTTPS with a
> valid certificate, keep sign-up closed, use strong passwords and keep TapBook
> updated; a VPN is the safest choice.

## TapBook on a VPS

1. **A user for TapBook.** The installer refuses to run as root. If you only have
   root, create a user and switch to it:
   ```bash
   adduser tapbook
   ```
   ```bash
   usermod -aG sudo tapbook
   ```
   ```bash
   su - tapbook
   ```
   (On Fedora or Arch the group is `wheel` instead of `sudo`.)
2. **Install** the Linux package as that user (`bash install.sh`, choose
   *TapBook Server*). Choose sign-up *only from the terminal*: the installer asks
   for your account right away. Without a screen the server becomes a background
   service that starts with the machine and keeps running after you log out.
3. **Reach it**, in one of these ways:
   - **VPN (safest):** with WireGuard or Tailscale on the VPS and on your devices,
     no port is open to the Internet. Set `firewall = off` and open
     `https://<VPN address>:8000`. The certificate created by TapBook covers the
     VPN address too (also when the VPN starts after TapBook: it is added within a
     minute); `tapbook status` lists the addresses it covers.
   - **Domain and reverse proxy (recommended for a public server):** point a
     domain at the VPS and put [Caddy](https://caddyserver.com) in front of
     TapBook; Caddy gets and renews the Let's Encrypt certificate by itself.
     In `~/.local/share/tapbook/config.ini`:
     ```ini
     host = 127.0.0.1
     https = false
     behind_proxy = true
     firewall = off
     ```
     and in `/etc/caddy/Caddyfile`:
     ```
     notes.example.org {
         reverse_proxy 127.0.0.1:8000
         request_body {
             max_size 110MB
         }
     }
     ```
     Then open ports 80 and 443 (for example `sudo ufw allow 80,443/tcp`).
   - **Own certificate, no proxy:** set `tls_cert` and `tls_key` to the
     certificate files (for example those of certbot). TapBook picks up the
     renewed certificate within a minute, without restarting. The files must be
     readable by the TapBook user. Open the port yourself (`sudo ufw allow 8000/tcp`)
     and set `firewall = off`.
   - **TapBook's own certificate:** it works as at home (install the certificate
     on each device); open the port and set `firewall = off`.
4. After a change of `config.ini`: `tapbook service restart`.

**Moving from your computer to the VPS:** `tapbook config export` (or
*Configurazione → Esporta* in the panel) writes a complete `config.ini` to copy to
the VPS; then let TapBook Sync upload your documents.

**Commands on the server**

| Command | What it does |
|---|---|
| `tapbook status` | Version, settings in use, accounts, service, certificate fingerprint |
| `tapbook user add <name>` | Create an account (also `passwd`, `del`, `list`) |
| `tapbook device list` | Computers paired with TapBook Sync |
| `tapbook device revoke <id>` | Unpair a computer |
| `tapbook config show` | Every setting, its value and where it comes from |
| `tapbook config export` | A complete `config.ini` for another server |
| `tapbook service enable` / `disable` / `restart` | The background service |
| `tapbook logs -f` | Messages of the service (failed logins included) |

## Troubleshooting

- **The document shows one more device after reloading the page:** fixed in
  0.1.1. Each browser tab is recognised, so a reload replaces its previous
  connection.
- **Something went wrong in Safari on the iPad:** errors of the interface are
  reported to the computer and saved in `client-errors.log` in the data folder
  (`~/.local/share/tapbook/instance` on Linux, `%LOCALAPPDATA%\TapBook` on
  Windows). The file never grows beyond 256 KB.
- **The editor shows "Il computer non risponde" (the computer is not answering):**
  the network between the iPad and the server is losing data (typical with a
  phone hotspot). The changes are kept; after 20 seconds the editor sends them
  again on a new connection, and the server recognises a change it already
  received, so it is never applied twice. When leaving the editor, TapBook waits
  a few seconds and then asks whether to leave anyway.
- **TapBook Sync says "Conferma richiesta":** many files are about to be deleted at
  once (more than 10 and more than 30% of them). Check that the folder is the
  right one, then press *Elimina comunque*, or pause the synchronisation.
- **The control panel does not open:** the error is saved in
  `desktop-error.log` in the installation folder and shown in a message box.

## Configuration

TapBook works without any configuration. To change something, copy
`config.example.ini` to `config.ini` in the installation folder and edit it.
Every value can also be set with an environment variable, `NOTES_<NAME>` (for
example `NOTES_PORT=8443`).

| Setting | Default | Meaning |
|---|---|---|
| `port` | `8000` | Port of the server |
| `notes_root` | `~/Note` | Folder with one subfolder per user |
| `allow_registration` | `true` | Whether accounts can be created from the login page (`false`: only with `tapbook user add`) |
| `session_hours` | `12` | How long a login lasts |
| `max_upload_mb` | `100` | Largest PDF or photo that can be uploaded |
| `edit_idle_minutes` | `15` | Idle time after which an open document is saved and paused |
| `https` | `true` | Encrypted connection |
| `tls_cert`, `tls_key` | empty | Your own certificate and key (empty: the one created by TapBook) |
| `behind_proxy` | `false` | TapBook is behind a reverse proxy that handles HTTPS |
| `firewall` | `auto` | `auto`, `on` or `off` |
| `update_check` | `true` | Check GitHub for new releases when the panel opens |

## Running from source

The app needs Python 3.10 or newer.

**Linux**
```bash
git clone <this repository> tapbook
```
```bash
cd tapbook
```
```bash
python3 -m venv .venv
```
```bash
.venv/bin/pip install -r requirements.txt
```
Then start the control panel:
```bash
.venv/bin/python -m app desktop
```
or the server in the terminal (Ctrl+C stops it):
```bash
.venv/bin/python -m app serve
```

**Windows:** the same steps, with `py -3 -m venv .venv` and `.venv\Scripts\python`.

**Other commands** (they all start with `python -m app`):

| Command | What it does |
|---|---|
| `user add <name>` | Create an account |
| `user passwd <name>` | Change a password (computers paired with TapBook Sync must connect again) |
| `user del <name>` | Delete an account (the documents stay on disk) |
| `user list` | List the accounts |
| `status`, `config show`, `config export` | See [TapBook on a VPS](#tapbook-on-a-vps) |
| `device list`, `device revoke <id>` | Computers paired with TapBook Sync |

TapBook Sync from source: `.venv/bin/python -m app.syncclient` (the window) or
`… service` (the background service).

**Installing from the source folder:** `bash installer/linux/install.sh` on Linux.
On Windows, right-click `installer\windows\Install TapBook.cmd` and choose *Run as
administrator*.

**Running the tests** (security, saving, collaboration, shapes, backgrounds,
server mode, synchronisation):
```bash
.venv/bin/python tests/run_all.py
```
`tests/bench.py` measures the speed of the main server operations.

**Building the release packages:**
```bash
python3 installer/crea_pacchetti.py
```
It writes the Linux and Windows archives to `dist/`, ready to attach to a GitHub
release. The release tag must be `v` + the `__version__` in `app/__init__.py`, so
the update check can compare them.

## Made with vibe coding

TapBook was built with **vibe coding**: the author described in plain language
what the app should do and how it should look. An AI coding assistant,
[Claude Code](https://claude.com/claude-code) by Anthropic, wrote the code. The
author drove the design, tried every feature on a real iPad with the Apple
Pencil, reported what was wrong and asked for changes until it worked as intended.

What this means in practice:

- Most of the code was not typed by hand. It was generated, reviewed through
  testing and refined over many iterations.
- Security was treated as a requirement from the start. The login was attacked
  on purpose and the files were tested with malicious names and uploads. The
  firewall rules were checked to open and close correctly even when the server
  is killed. The move from MariaDB to SQLite was checked for any loss of security.
- It is still a hobby project without a professional security audit. Read the
  code and use it on networks you trust.

Bug reports and pull requests are welcome.

## License

Copyright © 2026 Guido Schiattarella

TapBook is free software. You can redistribute it and/or modify it under the
terms of the **GNU Affero General Public License** as published by the Free
Software Foundation, either version 3 of the License, or (at your option) any
later version.

TapBook is distributed in the hope that it will be useful, but **without any
warranty**; without even the implied warranty of merchantability or fitness for a
particular purpose. See the [LICENSE](LICENSE) file for the full text.

In short: you may use, study, change and share TapBook. If you distribute a
modified version, **or let other people use a modified version over a network**
(for example by hosting it as a service), you must offer them its source code
under the same license.

### Third-party components

| Component | License |
|---|---|
| [PyMuPDF](https://pymupdf.readthedocs.io/) | GNU AGPL v3.0 (or Artifex commercial license) |
| [pdf.js](https://mozilla.github.io/pdf.js/) (bundled in `app/view/static/vendor/pdfjs`, with its license files) | Apache 2.0 |
| [Flask](https://flask.palletsprojects.com/), Werkzeug, Jinja2, Click, ItsDangerous, MarkupSafe | BSD-3-Clause |
| [Cheroot](https://cheroot.cherrypy.dev/) | BSD-3-Clause |
| [Pillow](https://python-pillow.org/) | MIT-CMU |
| [cryptography](https://cryptography.io/) | Apache 2.0 or BSD-3-Clause |
| [PyMySQL](https://github.com/PyMySQL/PyMySQL) | MIT (only to migrate users from old versions) |
| Libraries installed with PyMuPDF (NumPy, ONNX Runtime, NetworkX, protobuf, PyYAML, psutil, tabulate, FlatBuffers) | BSD, MIT or Apache 2.0 |

All of them are compatible with the GNU AGPL v3. The Python libraries are not
included in this repository or in the release packages: the installers download
them from PyPI.
