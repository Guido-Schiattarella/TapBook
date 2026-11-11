#!/usr/bin/env bash
# TapBook — installation on Linux (in the home folder; the system is touched
# only to install missing packages).
#
#   bash installer/linux/install.sh [--server | --client] [--update | --fresh]
#
# It asks what to install:
#   * TapBook Server: the app (the one used from the iPad's browser). On a
#     computer with a screen it gets its control panel; without one (a VPS) it
#     becomes a background service that starts with the machine;
#   * TapBook Sync: keeps a folder of this computer aligned with a TapBook Server.
# If it is already installed, it asks whether to update it (settings untouched,
# no questions) or to install it from scratch (all the questions again: the old
# settings are kept aside as a backup; documents and accounts stay where they are).
#
# 1. checks Python 3.10+, the venv module and Tk (for the windows) and, if they
#    are missing, installs them with the distribution's package manager (asks first);
# 2. copies the application to ~/.local/share/tapbook (server) or
#    ~/.local/share/tapbook-sync (client);
# 3. prepares the Python environment and installs the libraries one by one;
# 4. checks that it really starts;
# 5. creates the application menu shortcut and the `tapbook` (or `tapbook-sync`)
#    command; adds the uninstaller.
# A progress bar shows how far the installation has got; the full output of every
# command goes to install.log in the installation folder.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
BIN="$HOME/.local/bin"
APPS="$DATA_HOME/applications"
ICONS="$DATA_HOME/icons/hicolor"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/app/__init__.py")"
HAS_SCREEN=""; [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && HAS_SCREEN=1

MODE=""; ACTION=""; REGISTRATION=""
for arg in "$@"; do
    case "$arg" in
        --server) MODE=server ;;
        --client) MODE=client ;;
        --update) ACTION=update ;;
        --fresh) ACTION=fresh ;;
        --registration=open) REGISTRATION=open ;;
        --registration=closed) REGISTRATION=closed ;;
        *) echo "Unknown option: $arg"; exit 2 ;;
    esac
done

blue=$'\e[1;34m'; cyan=$'\e[36m'; red=$'\e[1;31m'; dim=$'\e[2m'; bold=$'\e[1m'; off=$'\e[0m'
[ -t 1 ] || { blue=; cyan=; red=; dim=; bold=; off=; }
LOG=/dev/null

# --- progress bar and log -----------------------------------------------------------
# progress PERCENT "what is happening": one bar line per stage, the details below it.
progress() {
    local pct=$1 width=30 filled bar
    filled=$(( pct * width / 100 ))
    printf -v bar '%*s' "$filled" ''; bar=${bar// /█}
    printf -v rest '%*s' $(( width - filled )) ''; rest=${rest// /░}
    printf '\n  %s%s%s%s %3d%%  %s\n' "$cyan" "$bar" "$rest" "$off" "$pct" "$2"
    printf '\n== %s (%d%%)\n' "$2" "$pct" >> "$LOG" || true
}
info() {
    printf '      %s%s%s\n' "$dim" "$*" "$off"
    printf '%s\n' "$*" >> "$LOG" || true
}
fail() {
    printf '\n  %sError:%s %s\n' "$red" "$off" "$*" >&2
    [ -f "$LOG" ] && printf '  Full log: %s\n' "$LOG" >&2
    exit 1
}
# Runs a command: all of its output goes to the log, the meaningful lines
# (matching FILTER) are shown on screen.
run() {
    local filter=$1; shift
    printf '$ %s\n' "$*" >> "$LOG"
    "$@" 2>&1 | tee -a "$LOG" | { grep -E --line-buffered "$filter" || true; } |
        sed -u -E "s/^Requirement already satisfied: ([^ ]+) .*/Already installed: \1/; s/^/      $dim/; s/\$/$off/"
}
# choose "question" "1st option" "2nd option" → prints 1 or 2
choose() {
    local answer
    printf '\n  %s%s%s\n' "$bold" "$1" "$off" >&2
    printf '    1) %s\n    2) %s\n' "$2" "$3" >&2
    while true; do
        read -r -p "  Choice [1/2]: " answer
        case "$answer" in 1|2) echo "$answer"; return ;; esac
    done
}

if [ "$(id -u)" -eq 0 ]; then
    fail "do not run the installation as root: TapBook installs in a user's home folder and never runs as root.
  On a VPS where you only have root, create a user first, then install as that user:
      adduser tapbook && usermod -aG sudo tapbook      (Fedora/Arch: wheel instead of sudo)
      su - tapbook
  and run «bash install.sh» again from that user (copy the folder to its home)."
fi
[ -f "$SRC/app/__main__.py" ] || fail "application files not found next to the installer ($SRC)."
printf '\n  %sTapBook %s%s — installation\n' "$blue" "$VERSION" "$off"

# --- what to install -------------------------------------------------------------------
if [ -z "$MODE" ]; then
    case "$(choose "What do you want to install?" \
        "TapBook Server — the notes app, used from the iPad's browser (this computer or a VPS)" \
        "TapBook Sync — keeps a folder of this computer aligned with a TapBook Server")" in
        1) MODE=server ;; 2) MODE=client ;;
    esac
fi
if [ "$MODE" = server ]; then
    NAME="TapBook Server"; DEST="$DATA_HOME/tapbook"; COMMAND=tapbook; SERVICE=tapbook
else
    NAME="TapBook Sync"; DEST="$DATA_HOME/tapbook-sync"; COMMAND=tapbook-sync; SERVICE=tapbook-sync
fi
EXISTING=""; [ -d "$DEST/app" ] && EXISTING=1
if [ -z "$ACTION" ]; then
    if [ -n "$EXISTING" ]; then
        case "$(choose "$NAME is already installed. What do you want to do?" \
            "Update it — settings untouched, no questions" \
            "Install it from scratch — all the settings again (the old ones are kept as a backup; documents and accounts stay)")" in
            1) ACTION=update ;; 2) ACTION=fresh ;;
        esac
    else
        ACTION=fresh
    fi
fi
[ -n "$EXISTING" ] || ACTION=fresh

# A server without a screen (VPS) runs as a background service.
SERVER_SERVICE=""
if [ "$MODE" = server ] && { [ -z "$HAS_SCREEN" ] || [ -f "$CONFIG_HOME/systemd/user/tapbook.service" ]; }; then
    SERVER_SERVICE=1
fi

# Sign-up (server installed from scratch)
if [ "$MODE" = server ] && [ "$ACTION" = fresh ] && [ -z "$REGISTRATION" ]; then
    case "$(choose "Who can create an account?" \
        "Anyone who reaches the server, from the login page" \
        "Only you, from the terminal of this machine with «tapbook user add» (recommended on the Internet)")" in
        1) REGISTRATION=open ;; 2) REGISTRATION=closed ;;
    esac
fi

# Update: the app must not be running while its files are being replaced. A
# background service is stopped here and started again at the end.
user_systemctl() {
    XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" systemctl --user "$@"
}
RESTART_SERVICE=""
if command -v systemctl >/dev/null && user_systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
    user_systemctl stop "$SERVICE" 2>/dev/null || true
    RESTART_SERVICE=1
fi
if [ "$MODE" = server ]; then
    if pgrep -f "$DEST/.venv/bin/python -m app (desktop|serve)" >/dev/null 2>&1; then
        fail "TapBook Server is open: close its window (or stop the server) and run the installation again."
    fi
else
    pkill -f "$DEST/.venv/bin/python -m app.syncclient" 2>/dev/null || true     # resumes where it stopped
fi
mkdir -p "$DEST"
chmod 700 "$DEST"
LOG="$DEST/install.log"
printf '%s %s installation (%s), %s\n' "$NAME" "$VERSION" "$ACTION" "$(date '+%Y-%m-%d %H:%M:%S')" > "$LOG"
chmod 600 "$LOG"

# --- 0. administrator password ----------------------------------------------------------
# Always asked (sudo -k: even if sudo remembers it from a command run shortly before):
# it confirms the installation and that the computer can be administered. At the
# end sudo forgets it.
progress 0 "Administrator password"
command -v sudo >/dev/null || fail "sudo not found: it is needed to install the dependencies."
info "Installing $NAME requires the administrator password."
sudo -k
trap 'sudo -k 2>/dev/null || true' EXIT
sudo -v -p "      Administrator password: " || fail "administrator password not confirmed: installation cancelled."
info "Password confirmed."

# --- 1. dependencies -----------------------------------------------------------------
progress 10 "Checking the dependencies"
python_ok() { python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; }
venv_ok()   { python3 -c 'import venv, ensurepip' 2>/dev/null; }
tk_ok()     { python3 -c 'import tkinter' 2>/dev/null; }
NEED_TK=""
{ [ "$MODE" = client ] || [ -n "$HAS_SCREEN" ]; } && NEED_TK=1      # windows only where there is a screen

missing=()
if command -v pacman >/dev/null; then
    pm=(sudo pacman -S --needed --noconfirm); python_ok || missing+=(python)
    [ -z "$NEED_TK" ] || tk_ok || missing+=(tk)
elif command -v apt-get >/dev/null; then
    pm=(sudo apt-get install -y); python_ok || missing+=(python3)
    venv_ok || missing+=(python3-venv); [ -z "$NEED_TK" ] || tk_ok || missing+=(python3-tk)
elif command -v dnf >/dev/null; then
    pm=(sudo dnf install -y); python_ok || missing+=(python3)
    [ -z "$NEED_TK" ] || tk_ok || missing+=(python3-tkinter)
elif command -v zypper >/dev/null; then
    pm=(sudo zypper --non-interactive install); python_ok || missing+=(python3)
    [ -z "$NEED_TK" ] || tk_ok || missing+=(python3-tk)
else
    pm=()
fi

if [ ${#missing[@]} -gt 0 ]; then
    [ ${#pm[@]} -gt 0 ] || fail "Python 3.10+ with venv (and Tk for the windows) is required: install it with the package manager and run the installation again."
    info "Missing: ${missing[*]}"
    read -r -p "      Install them now with «${pm[*]} ${missing[*]}»? [Y/n] " answer
    case "${answer,,}" in n|no) fail "installation cancelled." ;; esac
    progress 15 "Installing the system packages: ${missing[*]}"
    [ "${pm[1]}" = apt-get ] && run '.' sudo apt-get update
    run '.' "${pm[@]}" "${missing[@]}" || fail "the system packages could not be installed."
fi
python_ok || fail "Python 3.10 or newer not found."
venv_ok || fail "the Python venv module is not available."
[ -z "$NEED_TK" ] || tk_ok || fail "Tk (tkinter) is not available: it is needed for the window."
info "Python $(python3 -c 'import platform; print(platform.python_version())') found."

# --- 2. application files ------------------------------------------------------------
progress 25 "Copying the application to $DEST"
rm -rf "$DEST/app"                                    # the code is always replaced
cp -r "$SRC/app" "$DEST/app"
find "$DEST/app" -name __pycache__ -type d -prune -exec rm -rf {} +
info "$(find "$DEST/app" -type f | wc -l) application files copied."
STAMP="$(date '+%Y%m%d-%H%M%S')"
if [ "$MODE" = server ]; then
    cp "$SRC/requirements.txt" "$SRC/config.example.ini" "$DEST/"
    if [ "$ACTION" = fresh ]; then
        if [ -f "$DEST/config.ini" ]; then
            mv "$DEST/config.ini" "$DEST/config.ini.bak-$STAMP"
            info "Previous settings kept as config.ini.bak-$STAMP"
        fi
        flag=true; [ "$REGISTRATION" = closed ] && flag=false
        sed "s/^allow_registration = .*/allow_registration = $flag/" "$DEST/config.example.ini" > "$DEST/config.ini"
        sed -i '1,3c ; TapBook Server settings, written by the installer. Every value is explained in\n; config.example.ini; after a change restart TapBook (tapbook service restart on a VPS).' "$DEST/config.ini"
        info "Settings written: $DEST/config.ini (sign-up: $([ "$flag" = true ] && echo "from the login page" || echo "terminal only"))"
    else
        [ -f "$DEST/config.ini" ] || { [ -f "$SRC/config.ini" ] && cp "$SRC/config.ini" "$DEST/" && info "Settings (config.ini) copied."; } || true
        info "Settings untouched (update)."
    fi
    if [ ! -d "$DEST/instance" ] && [ -d "$SRC/instance" ]; then
        info "Copying the project's internal data (users, HTTPS certificate, session key)."
        cp -a "$SRC/instance" "$DEST/instance"
    fi
else
    if [ "$ACTION" = fresh ] && [ -d "$CONFIG_HOME/tapbook-sync" ]; then
        mv "$CONFIG_HOME/tapbook-sync" "$CONFIG_HOME/tapbook-sync.bak-$STAMP"
        info "Previous settings kept as $CONFIG_HOME/tapbook-sync.bak-$STAMP (the synchronised folder is untouched)."
    fi
fi

# --- 3. Python environment ------------------------------------------------------------
progress 35 "Preparing the Python environment"
if [ -x "$DEST/.venv/bin/python" ]; then
    info "Existing environment kept."
else
    run '.' python3 -m venv "$DEST/.venv" || fail "the Python environment could not be created."
    info "Environment created in $DEST/.venv"
fi
PY="$DEST/.venv/bin/python"
if [ "$MODE" = server ]; then
    PIP=("$PY" -m pip install --disable-pip-version-check --progress-bar off)
    PIP_SHOW='^(Collecting|Downloading|Installing|Successfully|Requirement already satisfied: [^ ]+==|ERROR|error)'
    run "$PIP_SHOW" "${PIP[@]}" --upgrade pip || fail "pip could not be updated (an Internet connection is required)."
    # One library at a time: the bar moves forward with each of them.
    mapfile -t packages < <(sed -e 's/#.*//' -e 's/[[:space:]]//g' "$DEST/requirements.txt" | grep -v '^$')
    for i in "${!packages[@]}"; do
        pkg=${packages[$i]}
        progress $(( 40 + 40 * i / ${#packages[@]} )) "Installing the libraries ($(( i + 1 ))/${#packages[@]}): ${pkg%%==*}"
        run "$PIP_SHOW" "${PIP[@]}" "$pkg" || fail "the library ${pkg%%==*} could not be installed (an Internet connection is required)."
    done
else
    info "TapBook Sync uses only Python's standard library: nothing to download."
fi

# --- 4. startup check -----------------------------------------------------------------
progress 80 "Checking that $NAME starts"
run 'Error' "$PY" -m compileall -q "$DEST/app" || true      # faster first start
if [ "$MODE" = server ]; then
    (cd "$DEST" && run '.' "$PY" -c "import app, flask, cheroot, pymupdf, PIL, cryptography") \
        || fail "the libraries were not installed correctly."
    info "Libraries loaded correctly."
    if [ -n "$HAS_SCREEN" ]; then
        (cd "$DEST" && run '.' "$PY" -m app desktop --check) || fail "the TapBook window does not start (details in the log)."
        info "The control panel opens correctly."
    fi
else
    (cd "$DEST" && run '.' "$PY" -c "import app.syncclient.service, app.syncclient.engine") || fail "TapBook Sync does not load."
    if [ -n "$HAS_SCREEN" ]; then
        (cd "$DEST" && run '.' "$PY" -m app.syncclient window --check) || fail "the TapBook Sync window does not start (details in the log)."
        info "The window opens correctly."
    fi
fi

# --- 5. command, shortcuts, service ----------------------------------------------------------
progress 90 "Creating the command and the shortcuts"
mkdir -p "$BIN" "$APPS" "$ICONS/256x256/apps" "$ICONS/128x128/apps" "$ICONS/64x64/apps"
if [ "$MODE" = server ]; then
    cat > "$BIN/tapbook" <<EOF
#!/bin/sh
# TapBook Server: control panel (window to start and stop the server); without a
# screen (e.g. a VPS over SSH) the state of the server instead.
# "tapbook user add", "tapbook status" and the other commands: tapbook --help
cd "$DEST" || exit 1
if [ \$# -eq 0 ]; then
    if [ -n "\${DISPLAY:-}\${WAYLAND_DISPLAY:-}" ]; then set -- desktop; else set -- status; fi
fi
exec "$DEST/.venv/bin/python" -m app "\$@"
EOF
    ICON_NAME=tapbook; ENTRY="$APPS/tapbook.desktop"
    ENTRY_TEXT="Name=TapBook Server
GenericName=Notes server
Comment=Start and stop the TapBook server to write on PDFs from the iPad
Exec=$BIN/tapbook
StartupWMClass=Tapbook"
else
    cat > "$BIN/tapbook-sync" <<EOF
#!/bin/sh
# TapBook Sync: the window; "tapbook-sync status" shows what the service is doing.
cd "$DEST" || exit 1
exec "$DEST/.venv/bin/python" -m app.syncclient "\$@"
EOF
    ICON_NAME=tapbook-sync; ENTRY="$APPS/tapbook-sync.desktop"
    ENTRY_TEXT="Name=TapBook Sync
GenericName=Folder synchronisation
Comment=Keep a folder of this computer aligned with TapBook Server
Exec=$BIN/tapbook-sync
StartupWMClass=Tapbooksync"
fi
chmod 755 "$BIN/$COMMAND"
info "Command: $BIN/$COMMAND"
cp "$DEST/app/view/static/img/logo.png" "$ICONS/256x256/apps/$ICON_NAME.png"
cp "$DEST/app/view/static/img/logo-128.png" "$ICONS/128x128/apps/$ICON_NAME.png"
cp "$DEST/app/view/static/img/favicon.png" "$ICONS/64x64/apps/$ICON_NAME.png"
if [ -n "$HAS_SCREEN" ] || [ "$MODE" = client ]; then
    cat > "$ENTRY" <<EOF
[Desktop Entry]
Type=Application
$ENTRY_TEXT
Icon=$ICONS/256x256/apps/$ICON_NAME.png
Terminal=false
Categories=Office;
Keywords=notes;pdf;ipad;pencil;sync;
EOF
    info "Menu entry: $ENTRY"
    command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" >/dev/null 2>&1 || true
    command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$ICONS" >/dev/null 2>&1 || true
fi
if [ "$MODE" = server ]; then
    cp "$SRC/installer/linux/uninstall.sh" "$DEST/uninstall.sh"
else
    cp "$SRC/installer/linux/uninstall-sync.sh" "$DEST/uninstall.sh"
fi
chmod 755 "$DEST/uninstall.sh"

# First account, when sign-up is closed and there is none yet
if [ "$MODE" = server ] && [ "$ACTION" = fresh ] && [ "$REGISTRATION" = closed ]; then
    if (cd "$DEST" && "$PY" -m app user list 2>/dev/null | grep -q "Nessun utente"); then
        printf '\n  %sCreate your account%s (sign-up from the web is closed)\n' "$bold" "$off"
        while true; do
            read -r -p "      Username: " first_user
            (cd "$DEST" && "$PY" -m app user add "$first_user") && break
        done
    else
        info "Accounts already present: kept."
    fi
fi

if [ "$MODE" = server ] && [ -n "$SERVER_SERVICE" ]; then
    progress 95 "Starting the background service"
    sudo -v 2>/dev/null || true             # lingering may need the administrator
    (cd "$DEST" && "$PY" -m app service enable) 2>&1 | tee -a "$LOG" | sed "s/^/      /" \
        || fail "the background service could not be started (details: tapbook logs)."
elif [ "$MODE" = client ]; then
    progress 95 "Starting TapBook Sync in the background (at every login)"
    (cd "$DEST" && "$PY" -m app.syncclient autostart) >> "$LOG" 2>&1 || info "Automatic start not set: open TapBook Sync once."
elif [ -n "$RESTART_SERVICE" ]; then
    user_systemctl start "$SERVICE" 2>/dev/null || true
fi

progress 100 "Done"
printf '\n  %s%s is installed.%s\n' "$blue" "$NAME" "$off"
if [ "$MODE" = server ] && [ -n "$SERVER_SERVICE" ]; then
    echo "  The server runs in the background and starts with the machine."
    echo "  State: tapbook status   ·   Messages: tapbook logs -f   ·   Users: tapbook user add <name>"
    echo "  Reach it from the Internet: see «TapBook on a VPS» in the README (port, HTTPS, proxy)."
elif [ "$MODE" = server ]; then
    echo "  Open it from the application menu (TapBook Server) or with the command: tapbook"
    echo "  Documents: ~/Note"
else
    echo "  Open TapBook Sync from the application menu (or: tapbook-sync), connect the server and choose the folder."
fi
echo "  Uninstall: $DEST/uninstall.sh   ·   Installation log: $LOG"
# ~/.local/bin is in PATH only if it existed at login (Ubuntu, Debian…): for a first
# installation the command is found only from the next login. The profile gets
# the folder if it does not mention it already, and the command for right now is shown.
case ":$PATH:" in
    *":$BIN:"*) ;;
    *)
        for profile in "$HOME/.profile" "$HOME/.bash_profile" "$HOME/.zprofile"; do
            case "$profile" in
                "$HOME/.profile") ;;                                   # always (read by sh, bash, dash)
                *) [ -f "$profile" ] || continue ;;                    # only if the shell uses it
            esac
            if ! grep -qs '\.local/bin' "$profile"; then
                printf '\n# Added by the TapBook installer: commands installed in ~/.local/bin\n[ -d "$HOME/.local/bin" ] && PATH="$HOME/.local/bin:$PATH"\n' >> "$profile"
                info "Added ~/.local/bin to the PATH in $profile"
            fi
        done
        printf '\n  %sThe «%s» command works from the next login. In this terminal, run first:%s\n' "$bold" "$COMMAND" "$off"
        printf '      source ~/.profile\n'
        printf '  %s(or use the full path: %s)%s\n' "$dim" "$BIN/$COMMAND" "$off"
        ;;
esac
echo
