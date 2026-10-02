#!/bin/bash
# Install Searchlight as a background service on macOS (e.g. a Mac mini).
#
#   ./scripts/install-macos.sh            install / update and start
#   ./scripts/install-macos.sh login      log in to Facebook (pauses the service)
#   ./scripts/install-macos.sh uninstall  stop and remove the service
#
# It runs as a LaunchAgent in your user session: it starts when you log in,
# restarts if it crashes, and keeps the Mac awake (`caffeinate`) while it runs.
set -euo pipefail

LABEL="ch.searchlight.watch"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$HOME/.searchlight"
LOG="$DATA/searchlight.log"

if [[ "${1:-}" == "login" ]]; then
  # The service and `login` share one browser profile, which Chromium can
  # only open once at a time, so pause the service meanwhile.
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  (cd "$REPO" && .venv/bin/python -m searchlight -c config.yaml login) || true
  [[ -f "$PLIST" ]] && launchctl bootstrap "gui/$(id -u)" "$PLIST"
  exit 0
fi

if [[ "${1:-}" == "uninstall" ]]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Searchlight service removed. Your data in $DATA was kept."
  exit 0
fi

cd "$REPO"
if [[ ! -f config.yaml ]]; then
  cp config.example.yaml config.yaml
  echo "Created config.yaml - edit it (your items + ntfy topic), then run this script again."
  exit 1
fi

PY="$(command -v python3 || true)"
if [[ -z "$PY" ]] || ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
  echo "Python 3.10+ is needed. Install it with: brew install python  (or from python.org)"
  exit 1
fi

echo "Installing dependencies..."
[[ -d .venv ]] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
.venv/bin/playwright install chromium

mkdir -p "$DATA" "$(dirname "$PLIST")"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string><string>-i</string>
    <string>$REPO/.venv/bin/python</string><string>-m</string><string>searchlight</string>
    <string>-c</string><string>$REPO/config.yaml</string><string>watch</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo
echo "Searchlight is running and will start again whenever you log in."
echo "  Log:      tail -f $LOG"
echo "  Report:   .venv/bin/python -m searchlight report"
echo "  Facebook: ./scripts/install-macos.sh login"
echo "  Stop:     ./scripts/install-macos.sh uninstall"
