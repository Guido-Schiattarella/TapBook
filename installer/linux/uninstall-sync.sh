#!/usr/bin/env bash
# TapBook Sync — uninstallation on Linux. Stops the background service and removes
# the application, the shortcut and the icons. The synchronised folder is never
# touched (nor anything on the server); the settings (server address, the
# computer's token) are removed only after confirmation.
set -euo pipefail

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
DEST="$DATA_HOME/tapbook-sync"
BIN="$HOME/.local/bin"
ICONS="$DATA_HOME/icons/hicolor"

read -r -p "Uninstall TapBook Sync? The synchronised folder and the files on the server are kept. [y/N] " answer
case "${answer,,}" in y|yes) ;; *) echo "Cancelled."; exit 0 ;; esac

[ -x "$DEST/.venv/bin/python" ] && (cd "$DEST" && "$DEST/.venv/bin/python" -m app.syncclient no-autostart >/dev/null 2>&1) || true
pkill -f "$DEST/.venv/bin/python -m app.syncclient" 2>/dev/null || true
rm -f "$BIN/tapbook-sync" "$DATA_HOME/applications/tapbook-sync.desktop"
rm -f "$ICONS"/{256x256,128x128,64x64}/apps/tapbook-sync.png
command -v update-desktop-database >/dev/null && update-desktop-database "$DATA_HOME/applications" >/dev/null 2>&1 || true
rm -rf "$DEST"

if [ -d "$CONFIG_HOME/tapbook-sync" ]; then
    read -r -p "Also delete the settings (server address, this computer's access)? [y/N] " answer
    case "${answer,,}" in
        y|yes) rm -rf "$CONFIG_HOME/tapbook-sync" ;;
        *) echo "Settings kept in $CONFIG_HOME/tapbook-sync (used if TapBook Sync is installed again)." ;;
    esac
fi
echo "TapBook Sync has been uninstalled. On the server you can also remove this computer: tapbook device list / revoke."
