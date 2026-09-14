#!/bin/bash
# Launch Chromium in kiosk mode on the Family Calendar, and keep it running.
#
# Started from the desktop session's autostart (see deploy_raspberry_pi.sh),
# so it inherits WAYLAND_DISPLAY / DISPLAY. Waits for the Flask service to
# answer before opening the browser, and relaunches the browser if it exits.

URL="${CALENDAR_URL:-http://localhost:5000/}"
HEALTH="${CALENDAR_URL:-http://localhost:5000/}health/"
PROFILE_DIR="${HOME}/.config/family-calendar-kiosk"

# Only one kiosk per session.
if pgrep -f "family-calendar-kiosk" >/dev/null 2>&1; then
  exit 0
fi

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

while true; do
  "$BROWSER" "${FLAGS[@]}" "$URL"
  echo "Browser exited; relaunching in 3s" >&2
  sleep 3
done
