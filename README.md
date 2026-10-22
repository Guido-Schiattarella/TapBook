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
and serves a notes app to the iPad on the same Wi-Fi network. You open it in
Safari, write on your PDFs with the Apple Pencil, and every change is saved
into the real PDF file on the computer about one second after you stop writing.
There is no cloud, no account with anyone and no subscription: the documents are
ordinary PDF files in a folder on your computer.

> [!NOTE]
> The interface of the app (web pages and control panel) is in **Italian**. The
> code, comments, installers and this documentation are in English.

## Features

**Writing**
- Pen and highlighter in 6 colours, with a thickness slider from very thin
  (0.2 pt) to very thick (16 pt); eraser in three sizes. The stroke follows the
  Pencil tip closely, with only light smoothing.
- Full Apple Pencil support with palm rejection: the Pencil writes and the finger
  scrolls. All the Pencil's high-frequency samples are used, so strokes are smooth.
- Shape recognition: draw a line, circle, ellipse, triangle, square or rectangle
  freehand and it becomes a clean shape. Hold the pen still at the end of a stroke
  to do the same without switching tools.
- Lasso: select strokes, text boxes and images, then move, recolour, duplicate or
  delete them.
- Text boxes typed from the keyboard, with adjustable font size. Tap a box in
  text mode to edit it again; the box can be moved, resized and deleted.
- Photos from the iPad camera or library. Photos can be moved, resized and
  deleted, even after the document is reopened.
- Keyboard shortcuts (with a keyboard connected to the iPad): **P** pen,
  **H** highlighter, **E** eraser, **L** lasso, **F** shapes, **T** text,
  **Esc** to leave a text box, **Cmd+Z** / **Cmd+Shift+Z** to undo and redo.
- Undo and redo for the whole session.
- Pinch to zoom from 0.5× to 10×, without redrawing the pages from scratch.

**Documents**
- Folders, new notebooks with a pastel colour and a page layout. Layouts: blank,
  ruled, grid, dotted, and Cornell ruled or Cornell grid.
- Import any PDF from the iPad, then add, remove or change the layout of pages.
- Search across all your documents: names, folders and the text inside the PDFs
  (lecture notes, slides…). Capitals and accents do not matter.
- Trash with restore, so deleted items can be brought back.
- The same document can be open on several devices at once: changes appear on
  all of them.

**Accounts**
- Several people can use the same computer: each person has an account and a
  private folder.
- Accounts are created from the login page; the first one is created on first start.
- Profile photo, password change and account deletion from the web. Deleting an
  account does not delete the documents.

**On the computer**
- A control panel window to start and stop the server. It shows the address to
  open on the iPad and tells you when a new version is available.
- Zero setup: the user database (SQLite), the HTTPS certificates and the
  configuration are created automatically.

## Installation

Download the package for your system from the
**[latest release](../../releases/latest)**.

### Linux

1. Extract `TapBook-<version>-linux.tar.gz`.
2. Open a terminal in the extracted folder and run:
   ```bash
   bash install.sh
   ```
3. The installer:
   - asks for the administrator password;
   - checks Python 3.10+, `venv` and Tk and installs whatever is missing with the
     distribution's package manager (it asks first);
   - installs the app in `~/.local/share/tapbook`;
   - adds **TapBook** to the applications menu and the `tapbook` command.

   A progress bar shows each step. The full log is saved in
   `~/.local/share/tapbook/install.log`.

**Supported distributions:** recent versions of Arch Linux and its derivatives
(Manjaro, EndeavourOS…), Debian 12+, Ubuntu 22.04+ and its derivatives (Linux Mint,
Pop!_OS…), Fedora and openSUSE Tumbleweed. `sudo` is required. On other
distributions, install Python 3.10+ with `venv` and Tk yourself, then run the
installer.

### Windows

1. Extract `TapBook-<version>-windows.zip`. Extract the whole archive; do not run
   the installer from inside the zip.
2. Right-click **`Install TapBook.cmd`** and choose **Run as administrator**.
3. If Python 3.10+ is missing, the installer installs it with `winget` or with the
   official python.org installer, after checking its signature.
4. TapBook appears in the Start menu and on the desktop. The full log is saved in
   `%LOCALAPPDATA%\Programs\TapBook\install.log`.

It is made for Windows 10 and 11 (64-bit).

### Updating

Download the new package, close TapBook and run the installer again. Documents,
accounts and settings are kept. The control panel tells you when a new release
is out. It makes a single request to the GitHub API: no data is sent and nothing
is downloaded automatically.

### Uninstalling

- **Linux:** run `~/.local/share/tapbook/uninstall.sh`.
- **Windows:** go to *Settings → Apps → Installed apps → TapBook*.

Your documents are never deleted. The internal data (accounts, certificate) is
removed only if you confirm.

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
   *Registrati* (sign up) link.
5. Optional: tap *Share → Add to Home Screen* to open TapBook full screen, like an app.

Your documents are in the `Note` folder in your home folder:

| | Folder |
|---|---|
| Linux | `~/Note/<user>/` |
| Windows | `%USERPROFILE%\Note\<user>\` |

You can also add, copy or back up PDFs there directly from the computer.

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
- Each stroke is sent to the computer as soon as it is finished, so nothing is
  lost if Safari closes.
- About one second after the last change, the server writes the strokes, text
  boxes and images into the PDF with PyMuPDF.
- The annotations are kept editable inside the file. The PDF stays a normal PDF
  that any viewer can open, with your handwriting in it.

**Shared documents and conflicts**
- When the same document is open on several devices, the server merges their
  changes and sends each device the changes of the others.
- If a PDF is changed on the computer while it is open on the iPad, TapBook
  notices it. One version wins and the other is kept in the trash, so nothing is
  overwritten silently.

**Code structure**
- The code follows the MVC pattern:
  - `app/model`: files, PDFs, users;
  - `app/control`: the logic;
  - `app/view`: the web pages and the API.
- Two more parts sit next to it:
  - `app/desktop`: the Tk control panel;
  - `app/system`: the code that is specific to each operating system
    (certificates, network, firewall, update check).

### Security

TapBook is meant for a **home network**, and it was designed to stay safe there:

| Area | How it is protected |
|---|---|
| Connection | HTTPS, with a private certificate authority created on your computer. You install it once on each iPad. |
| Passwords | Stored with scrypt and never in clear text. Logins are rate-limited and failed attempts lock the account for a while. Parallel login floods cannot exhaust memory. |
| Requests | Sessions are signed; requests carry CSRF protection. |
| Files | Uploaded files are checked. Names and paths are sanitised (no path traversal, symlinks or Windows device names), so each user can only reach their own folder. |
| Firewall | No need to disable it or open ports by hand (see below). |

**How the firewall is handled**
- When the server starts, TapBook opens its port **only for the local subnet**
  and **only while the server is running**. It works with ufw, firewalld,
  nftables, iptables (and tools built on them) and Windows Defender Firewall.
- The rule is temporary and is removed when the server stops, even if it crashes
  or is killed.
- The administrator password is asked at every start and never stored. No
  `sudoers` rule or permanent service is installed.

> [!WARNING]
> Do not expose TapBook to the Internet (port forwarding, public servers). It has
> not been audited for that use.

## Configuration

TapBook works without any configuration. To change something, copy
`config.example.ini` to `config.ini` in the installation folder and edit it.
Every value can also be set with an environment variable, `NOTES_<NAME>` (for
example `NOTES_PORT=8443`).

| Setting | Default | Meaning |
|---|---|---|
| `port` | `8000` | Port of the server |
| `notes_root` | `~/Note` | Folder with one subfolder per user |
| `allow_registration` | `true` | Whether new accounts can be created from the login page |
| `session_hours` | `12` | How long a login lasts |
| `max_upload_mb` | `100` | Largest PDF or photo that can be uploaded |
| `edit_idle_minutes` | `15` | Idle time after which an open document is saved and paused |
| `https` | `true` | Encrypted connection |
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
| `add-user <name>` | Create an account |
| `passwd <name>` | Change a password |
| `del-user <name>` | Delete an account (the documents stay on disk) |
| `list-users` | List the accounts |

**Installing from the source folder:** `bash installer/linux/install.sh` on Linux.
On Windows, right-click `installer\windows\Install TapBook.cmd` and choose *Run as
administrator*.

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
