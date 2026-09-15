#!/bin/bash
# Launch Chromium in kiosk mode on the Family Calendar.
#
# Started from the desktop session's autostart (see deploy_raspberry_pi.sh),
# so it inherits WAYLAND_DISPLAY / DISPLAY. Waits for the Flask service to
# answer before opening the browser. Relaunches the browser only when it
# crashes (non-zero exit); closing it deliberately (Alt+F4, or
# `launch-browser.sh stop`) leaves it closed so the desktop is usable.
#
#   launch-browser.sh          start (no-op if already running)
#   launch-browser.sh stop     close the kiosk until the next login
#   launch-browser.sh disable  also stop it starting at login (creates a flag file)
#   launch-browser.sh enable   remove the flag file

URL="${CALENDAR_URL:-http://localhost:5000/}"
HEALTH="${CALENDAR_URL:-http://localhost:5000/}health/"
PROFILE_DIR="${HOME}/.config/family-calendar-kiosk"
DISABLED_FLAG="$PROFILE_DIR/disabled"
PID_FILE="$PROFILE_DIR/launcher.pid"

mkdir -p "$PROFILE_DIR"

stop_kiosk() {
  if [ -f "$PID_FILE" ]; then
    kill "$(cat "$PID_FILE")" 2>/dev/null || true
    rm -f "$PID_FILE"
  fi
  pkill -f -- "--class=family-calendar-kiosk" 2>/dev/null || true
}

case "${1:-}" in
  stop)
    stop_kiosk
    echo "Kiosk stopped."
    exit 0
    ;;
  disable)
    touch "$DISABLED_FLAG"
    stop_kiosk
    echo "Kiosk stopped and disabled at login. Re-enable with: $0 enable"
    exit 0
    ;;
  enable)
    rm -f "$DISABLED_FLAG"
    echo "Kiosk enabled; it will start at the next login (or run $0 now)."
    exit 0
    ;;
esac

if [ -f "$DISABLED_FLAG" ]; then
  echo "Kiosk disabled by $DISABLED_FLAG" >&2
  exit 0
fi

# Only one launcher per session.
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  exit 0
fi
echo $$ > "$PID_FILE"
trap 'rm -f "$PID_FILE"' EXIT

BROWSER=""
for candidate in chromium chromium-browser; do
  if command -v "$candidate" >/dev/null 2>&1; then
    BROWSER="$candidate"
    break
  fi
done
if [ -z "$BROWSER" ]; then
  echo "No chromium binary found" >&2
  exit 1
fi

# Wait (up to two minutes) for the server so the first page is the app, not
# a connection error the user has to dismiss.
for _ in $(seq 1 60); do
  if curl -sf --max-time 2 "$HEALTH" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

FLAGS=(
  --kiosk
  --incognito
  --noerrdialogs
  --disable-infobars
  --disable-session-crashed-bubble
  --disable-pinch
  --overscroll-history-navigation=0
  --touch-events=enabled
  --autoplay-policy=no-user-gesture-required
  --check-for-update-interval=31536000
  --password-store=basic
  --disable-features=TranslateUI
  --hide-scrollbars
  --user-data-dir="$PROFILE_DIR"
  --class=family-calendar-kiosk
)
if [ -n "$WAYLAND_DISPLAY" ]; then
  FLAGS+=(--ozone-platform=wayland)
fi

# Relaunch on crashes only, with a backoff, and give up after repeated
# rapid crashes so a broken install does not lock the desktop.
crashes=0
while true; do
  started=$(date +%s)
  "$BROWSER" "${FLAGS[@]}" "$URL"
  code=$?
  if [ "$code" -eq 0 ]; then
    echo "Browser closed; not relaunching." >&2
    exit 0
  fi
  if [ $(( $(date +%s) - started )) -gt 60 ]; then
    crashes=0
  fi
  crashes=$((crashes + 1))
  if [ "$crashes" -ge 5 ]; then
    echo "Browser crashed $crashes times in a row; giving up." >&2
    exit "$code"
  fi
  echo "Browser exited with $code; relaunching in $((crashes * 3))s" >&2
  sleep $((crashes * 3))
done
