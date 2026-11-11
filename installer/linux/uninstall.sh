#!/usr/bin/env bash
# TapBook Server — uninstallation on Linux. Stops the background service (if
# any) and removes the application, shortcuts and icons.
# Documents (~/Note) are never touched; internal data (users, certificate,
# session key) is removed only after confirmation.
set -euo pipefail

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
DEST="$DATA_HOME/tapbook"
BIN="$HOME/.local/bin"
ICONS="$DATA_HOME/icons/hicolor"

read -r -p "Uninstall TapBook Server? Documents in ~/Note are kept. [y/N] " answer
case "${answer,,}" in y|yes) ;; *) echo "Cancelled."; exit 0 ;; esac

# The background service (server without a screen) is stopped and removed first.
[ -x "$DEST/.venv/bin/python" ] && (cd "$DEST" && "$DEST/.venv/bin/python" -m app service disable >/dev/null 2>&1) || true
if pgrep -f "$DEST/.venv/bin/python -m app (desktop|serve)" >/dev/null 2>&1; then
    echo "TapBook is open: close its window (or stop the server) and run the uninstallation again."
    exit 1
fi

rm -f "$BIN/tapbook" "$DATA_HOME/applications/tapbook.desktop"
rm -f "$ICONS"/{256x256,128x128,64x64}/apps/tapbook.png
command -v update-desktop-database >/dev/null && update-desktop-database "$DATA_HOME/applications" >/dev/null 2>&1 || true
rm -rf "$DEST/app" "$DEST/.venv" "$DEST/requirements.txt" "$DEST/config.example.ini" "$DEST/install.log" "$DEST/desktop-error.log"

if [ -d "$DEST/instance" ]; then
    read -r -p "Also delete the internal data (accounts, certificate installed on the iPad)? [y/N] " answer
    case "${answer,,}" in
        y|yes) rm -rf "$DEST/instance" ;;
        *) echo "Internal data kept in $DEST/instance (needed if TapBook is installed again)." ;;
    esac
fi
rm -f "$DEST/uninstall.sh"
rmdir "$DEST" 2>/dev/null || true
echo "TapBook Server has been uninstalled."
