#!/usr/bin/env bash
# TapBook — installation on Linux (in the home folder; the system is touched
# only to install missing packages).
#
#   bash installer/linux/install.sh
#
# 1. checks Python 3.10+, the venv module and Tk (for the window) and, if they are
#    missing, installs them with the distribution's package manager (asks first);
# 2. copies the application to ~/.local/share/tapbook (or $XDG_DATA_HOME/tapbook);
#    when installed from the project folder it also copies the internal data
#    (users, certificate already installed on the iPad, session key);
# 3. prepares the app's Python environment and installs the libraries one by one;
# 4. checks that the control panel really starts;
# 5. creates the application menu shortcut, with the logo, and the `tapbook`
#    command; adds the uninstaller.
# A progress bar shows how far the installation has got, with what is happening
# underneath; the full output of every command goes to install.log in the
# installation folder. Running it again updates the installation without losing
# data or settings.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
DEST="$DATA_HOME/tapbook"
BIN="$HOME/.local/bin"
APPS="$DATA_HOME/applications"
ICONS="$DATA_HOME/icons/hicolor"
LOG="$DEST/install.log"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/app/__init__.py")"

blue=$'\e[1;34m'; cyan=$'\e[36m'; red=$'\e[1;31m'; dim=$'\e[2m'; off=$'\e[0m'
[ -t 1 ] || { blue=; cyan=; red=; dim=; off=; }

# --- progress bar and log -----------------------------------------------------------
# progress PERCENT "what is happening": one bar line per stage, the details below it.
progress() {
    local pct=$1 width=30 filled bar
    filled=$(( pct * width / 100 ))
    printf -v bar '%*s' "$filled" ''; bar=${bar// /█}
    printf -v rest '%*s' $(( width - filled )) ''; rest=${rest// /░}
    printf '\n  %s%s%s%s %3d%%  %s\n' "$cyan" "$bar" "$rest" "$off" "$pct" "$2"
    [ -d "$DEST" ] && printf '\n== %s (%d%%)\n' "$2" "$pct" >> "$LOG" || true
}
info() {
    printf '      %s%s%s\n' "$dim" "$*" "$off"
    [ -d "$DEST" ] && printf '%s\n' "$*" >> "$LOG" || true
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

[ "$(id -u)" -ne 0 ] || fail "do not run the installation as root: TapBook installs in the home folder."
[ -f "$SRC/app/__main__.py" ] || fail "application files not found next to the installer ($SRC)."
printf '\n  %sTapBook %s%s — installation\n' "$blue" "$VERSION" "$off"

# Update: the app must not be running while its files are being replaced.
if pgrep -f "$DEST/.venv/bin/python -m app" >/dev/null 2>&1; then
    fail "TapBook is open: close its window (or stop the server) and run the installation again."
fi
mkdir -p "$DEST"
chmod 700 "$DEST"
printf 'TapBook %s installation, %s\n' "$VERSION" "$(date '+%Y-%m-%d %H:%M:%S')" > "$LOG"
chmod 600 "$LOG"

# --- 0. administrator password ----------------------------------------------------------
# Always asked (sudo -k: even if sudo remembers it from a command run shortly before):
# it confirms the installation and that the computer can be administered, which
# TapBook also needs to open its port in the firewall. At the end sudo forgets it.
progress 0 "Administrator password"
command -v sudo >/dev/null || fail "sudo not found: it is needed to install the dependencies and for the firewall."
info "Installing TapBook requires the administrator password."
sudo -k
trap 'sudo -k 2>/dev/null || true' EXIT
sudo -v -p "      Administrator password: " || fail "administrator password not confirmed: installation cancelled."
info "Password confirmed."

# --- 1. dependencies -----------------------------------------------------------------
progress 10 "Checking the dependencies"
python_ok() { python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; }
venv_ok()   { python3 -c 'import venv, ensurepip' 2>/dev/null; }
tk_ok()     { python3 -c 'import tkinter' 2>/dev/null; }

missing=()
if command -v pacman >/dev/null; then
    pm=(sudo pacman -S --needed --noconfirm); python_ok || missing+=(python); tk_ok || missing+=(tk)
elif command -v apt-get >/dev/null; then
    pm=(sudo apt-get install -y); python_ok || missing+=(python3)
    venv_ok || missing+=(python3-venv); tk_ok || missing+=(python3-tk)
elif command -v dnf >/dev/null; then
    pm=(sudo dnf install -y); python_ok || missing+=(python3); tk_ok || missing+=(python3-tkinter)
elif command -v zypper >/dev/null; then
    pm=(sudo zypper --non-interactive install); python_ok || missing+=(python3); tk_ok || missing+=(python3-tk)
else
    pm=()
fi

if [ ${#missing[@]} -gt 0 ]; then
    [ ${#pm[@]} -gt 0 ] || fail "Python 3.10+ with venv and Tk is required: install it with the package manager and run the installation again."
    info "Missing: ${missing[*]}"
    read -r -p "      Install them now with «${pm[*]} ${missing[*]}»? [Y/n] " answer
    case "${answer,,}" in n|no) fail "installation cancelled." ;; esac
    progress 15 "Installing the system packages: ${missing[*]}"
    run '.' "${pm[@]}" "${missing[@]}" || fail "the system packages could not be installed."
fi
python_ok || fail "Python 3.10 or newer not found."
venv_ok || fail "the Python venv module is not available."
tk_ok || fail "Tk (tkinter) is not available: it is needed for the TapBook window."
info "Python $(python3 -c 'import platform; print(platform.python_version())') with venv and Tk found."

# --- 2. application files ------------------------------------------------------------
progress 25 "Copying the application to $DEST"
rm -rf "$DEST/app"                                    # update: the code is replaced
cp -r "$SRC/app" "$DEST/app"
find "$DEST/app" -name __pycache__ -type d -prune -exec rm -rf {} +
info "$(find "$DEST/app" -type f | wc -l) application files copied."
cp "$SRC/requirements.txt" "$SRC/config.example.ini" "$DEST/"
[ -f "$DEST/config.ini" ] || { [ -f "$SRC/config.ini" ] && cp "$SRC/config.ini" "$DEST/" && info "Settings (config.ini) copied."; } || true
if [ ! -d "$DEST/instance" ] && [ -d "$SRC/instance" ]; then
    info "Copying the project's internal data (users, HTTPS certificate, session key)."
    cp -a "$SRC/instance" "$DEST/instance"
fi

# --- 3. Python environment ------------------------------------------------------------
progress 35 "Preparing the Python environment"
if [ -x "$DEST/.venv/bin/python" ]; then
    info "Existing environment kept (update)."
else
    run '.' python3 -m venv "$DEST/.venv" || fail "the Python environment could not be created."
    info "Environment created in $DEST/.venv"
fi
PY="$DEST/.venv/bin/python"
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

# --- 4. startup check -----------------------------------------------------------------
progress 80 "Checking that TapBook starts"
run 'Error' "$PY" -m compileall -q "$DEST/app" || true      # faster first start
(cd "$DEST" && run '.' "$PY" -c "import app, flask, cheroot, pymupdf, PIL, cryptography, tkinter") \
    || fail "the libraries were not installed correctly."
info "Libraries loaded correctly."
if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    (cd "$DEST" && run '.' "$PY" -m app desktop --check) || fail "the TapBook window does not start (details in the log)."
    info "The control panel opens correctly."
else
    info "No graphical session: window check skipped."
fi

# --- 5. shortcuts ---------------------------------------------------------------------
progress 90 "Creating the application menu shortcut"
mkdir -p "$BIN" "$APPS" "$ICONS/256x256/apps" "$ICONS/128x128/apps" "$ICONS/64x64/apps"
cat > "$BIN/tapbook" <<EOF
#!/bin/sh
# TapBook: control panel (window to start and stop the server).
# "tapbook serve" and the other "python -m app" commands work as in the terminal.
cd "$DEST" || exit 1
[ \$# -eq 0 ] && set -- desktop
exec "$DEST/.venv/bin/python" -m app "\$@"
EOF
chmod 755 "$BIN/tapbook"
info "Command: $BIN/tapbook"
cp "$DEST/app/view/static/img/logo.png" "$ICONS/256x256/apps/tapbook.png"
cp "$DEST/app/view/static/img/logo-128.png" "$ICONS/128x128/apps/tapbook.png"
cp "$DEST/app/view/static/img/favicon.png" "$ICONS/64x64/apps/tapbook.png"
cat > "$APPS/tapbook.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=TapBook
GenericName=Notes server
Comment=Start and stop the TapBook server to write on PDFs from the iPad
Exec=$BIN/tapbook
Icon=$ICONS/256x256/apps/tapbook.png
Terminal=false
Categories=Office;
Keywords=notes;pdf;ipad;pencil;
StartupWMClass=Tapbook
EOF
info "Menu entry: $APPS/tapbook.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$ICONS" >/dev/null 2>&1 || true
cp "$SRC/installer/linux/uninstall.sh" "$DEST/uninstall.sh"
chmod 755 "$DEST/uninstall.sh"

progress 100 "Done"
printf '\n  %sTapBook is installed.%s\n' "$blue" "$off"
echo "  Open it from the application menu (TapBook) or with the command: tapbook"
echo "  Documents: ~/Note   ·   Uninstall: $DEST/uninstall.sh"
echo "  Installation log: $LOG"
case ":$PATH:" in *":$BIN:"*) ;; *) printf '  %s(%s is not in PATH: type the «tapbook» command with its full path)%s\n' "$dim" "$BIN" "$off" ;; esac
echo
