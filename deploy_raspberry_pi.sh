#!/bin/bash
#
# Family Calendar & Photo Slideshow - Raspberry Pi deployment
#
# Targets Raspberry Pi OS Bookworm (64-bit) on a Raspberry Pi 4/5 with a
# touchscreen. Idempotent: safe to re-run after `git pull`.
#
# What it sets up:
#   * system packages (python, node, chromium, lgpio, ddcutil, emoji font)
#   * the Python virtualenv (via uv) and the compiled frontend (via npm)
#   * config.json (first run only; existing files are left alone)
#   * GPIO / backlight / i2c permissions for the service user
#   * the family-calendar systemd service (waitress + wsgi.py)
#   * the kiosk browser autostart for the desktop session
#   * screen blanking off
#
# Usage: sudo ./deploy_raspberry_pi.sh

set -euo pipefail

GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
section() { echo -e "\n${BLUE}===${NC} ${GREEN}$1${NC} ${BLUE}===${NC}\n"; }
status()  { echo -e "${YELLOW}-->${NC} $1"; }
error()   { echo -e "${RED}ERROR:${NC} $1"; exit 1; }

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
APP_DIR="$SCRIPT_DIR"
NODE_MAJOR=22

[ "$(id -u)" -eq 0 ] || error "Run with sudo: sudo $0"

# The user who will run the service and own the files: whoever invoked sudo.
APP_USER="${SUDO_USER:-$(logname 2>/dev/null || echo pi)}"
APP_HOME="$(getent passwd "$APP_USER" | cut -d: -f6)"
[ -n "$APP_HOME" ] || error "Cannot determine home directory for $APP_USER"
run_as_user() { sudo -u "$APP_USER" -H bash -c "cd '$APP_DIR' && $*"; }

ask_with_default() {
  local prompt="$1" default="$2" result=""
  read -r -p "$prompt [$default]: " result
  echo "${result:-$default}"
}

install_system_packages() {
  section "System packages"
  apt-get update
  apt-get install -y \
    git curl ca-certificates openssl \
    python3 python3-venv python3-dev \
    swig liblgpio-dev \
    ddcutil \
    fonts-noto-color-emoji \
    chromium 2>/dev/null || apt-get install -y chromium-browser

  if ! command -v node >/dev/null 2>&1 || [ "$(node -v | sed 's/v\([0-9]*\).*/\1/')" -lt 20 ]; then
    status "Installing Node.js $NODE_MAJOR (for building the frontend)..."
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
    apt-get install -y nodejs
  fi
  status "node $(node -v), npm $(npm -v)"

  if ! run_as_user "command -v uv >/dev/null 2>&1 || test -x '$APP_HOME/.local/bin/uv'"; then
    status "Installing uv (Python package manager) for $APP_USER..."
    run_as_user "curl -LsSf https://astral.sh/uv/install.sh | sh"
  fi
}

setup_permissions() {
  section "Hardware permissions"
  for group in gpio video i2c; do
    getent group "$group" >/dev/null || groupadd "$group"
    usermod -a -G "$group" "$APP_USER"
  done
  install -m 0644 "$APP_DIR/startup/99-family-calendar-backlight.rules" /etc/udev/rules.d/
  udevadm control --reload-rules
  udevadm trigger --subsystem-match=backlight || true
  # Enable I2C for ddcutil (HDMI monitors); harmless if unused.
  raspi-config nonint do_i2c 0 2>/dev/null || true
  status "$APP_USER is in the gpio, video and i2c groups"
}

build_application() {
  section "Application build"
  chown -R "$APP_USER:$APP_USER" "$APP_DIR"

  status "Python dependencies (uv sync)..."
  run_as_user "PATH=\$HOME/.local/bin:\$PATH uv sync --no-dev" \
    || error "uv sync failed. Missing swig/liblgpio-dev?"

  status "Frontend (npm ci && npm run build)..."
  run_as_user "cd frontend && npm ci --no-audit --no-fund && npm run build" \
    || error "Frontend build failed"
}

configure_application() {
  section "Configuration"
  if [ -f "$APP_DIR/config.json" ]; then
    status "config.json exists; leaving it alone"
    return
  fi
  echo "You can find your coordinates at https://www.latlong.net/"
  local family lat lon tz
  family=$(ask_with_default "Family name shown in the header" "Family")
  lat=$(ask_with_default "Latitude" "40.759010")
  lon=$(ask_with_default "Longitude" "-73.984474")
  tz=$(ask_with_default "Timezone" "America/New_York")

  python3 - "$APP_DIR" "$family" "$lat" "$lon" "$tz" <<'EOF'
import json, secrets, sys
app_dir, family, lat, lon, tz = sys.argv[1:]
with open(f"{app_dir}/config.default.json") as f:
    cfg = json.load(f)
cfg["app"]["family_name"] = family
cfg["app"]["secret_key"] = secrets.token_hex(32)
cfg["weather"].update({"latitude": float(lat), "longitude": float(lon), "timezone": tz})
with open(f"{app_dir}/config.json", "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
EOF
  chown "$APP_USER:$APP_USER" "$APP_DIR/config.json"
  status "Wrote $APP_DIR/config.json"

  if [ ! -f "$APP_DIR/src/google_integration/credentials.json" ]; then
    echo -e "${YELLOW}NOTICE:${NC} Google credentials.json not found. Calendar/Tasks sync needs it:"
    echo "  1. https://console.cloud.google.com/ -> create a project"
    echo "  2. Enable the Google Calendar API and Google Tasks API"
    echo "  3. Create OAuth credentials (Desktop application) and download credentials.json"
    echo "  4. Copy it to $APP_DIR/src/google_integration/credentials.json"
    echo "The first sync will open a browser window to authorise the account."
  fi
}

install_service() {
  section "systemd service"
  sed -e "s|/home/pi/family_calendar|$APP_DIR|g" \
      -e "s|^User=pi|User=$APP_USER|" \
      -e "s|^Group=pi|Group=$APP_USER|" \
      "$APP_DIR/startup/family-calendar.service" > /etc/systemd/system/family-calendar.service

  sed -e "s|/home/pi/family_calendar|$APP_DIR|g" "$APP_DIR/startup/health-monitor.sh" \
      > /usr/local/bin/family-calendar-health-monitor
  chmod +x /usr/local/bin/family-calendar-health-monitor
  touch /var/log/family-calendar-monitor.log
  chown "$APP_USER:$APP_USER" /var/log/family-calendar-monitor.log

  cat > /etc/systemd/system/family-calendar-monitor.service <<EOF
[Unit]
Description=Family Calendar Health Monitor
After=family-calendar.service
Requires=family-calendar.service

[Service]
Type=simple
ExecStart=/usr/local/bin/family-calendar-health-monitor
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

  # The in-app updater restarts the service; allow that one command without a password.
  cat > /etc/sudoers.d/family-calendar <<EOF
$APP_USER ALL=(root) NOPASSWD: /bin/systemctl restart family-calendar, /usr/bin/systemctl restart family-calendar, /usr/bin/apt-get install -y swig liblgpio-dev
EOF
  chmod 0440 /etc/sudoers.d/family-calendar

  systemctl daemon-reload
  systemctl enable family-calendar.service family-calendar-monitor.service
  systemctl restart family-calendar.service
  status "family-calendar.service enabled and started"
}

install_kiosk() {
  section "Kiosk browser"
  chmod +x "$APP_DIR/startup/launch-browser.sh"
  local autostart_dir="$APP_HOME/.config/autostart"
  sudo -u "$APP_USER" mkdir -p "$autostart_dir" "$APP_HOME/.config/labwc"

  cat > "$autostart_dir/family-calendar-kiosk.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Family Calendar Kiosk
Exec=/bin/bash $APP_DIR/startup/launch-browser.sh
X-GNOME-Autostart-enabled=true
EOF
  chown "$APP_USER:$APP_USER" "$autostart_dir/family-calendar-kiosk.desktop"

  # labwc (Pi OS Bookworm default since late 2024) reads this script.
  local labwc_autostart="$APP_HOME/.config/labwc/autostart"
  touch "$labwc_autostart"
  if ! grep -q "launch-browser.sh" "$labwc_autostart"; then
    echo "/bin/bash $APP_DIR/startup/launch-browser.sh &" >> "$labwc_autostart"
  fi
  chown "$APP_USER:$APP_USER" "$labwc_autostart"

  # wayfire (earlier Bookworm images).
  local wayfire_ini="$APP_HOME/.config/wayfire.ini"
  if [ -f "$wayfire_ini" ] && ! grep -q "launch-browser.sh" "$wayfire_ini"; then
    printf '\n[autostart]\nfamily_calendar = /bin/bash %s/startup/launch-browser.sh\n' "$APP_DIR" >> "$wayfire_ini"
  fi

  status "Disabling screen blanking..."
  raspi-config nonint do_blanking 1 2>/dev/null || true
  status "Kiosk autostart installed"
}

verify() {
  section "Verification"
  sleep 4
  if curl -sf http://localhost:5000/health/ >/dev/null; then
    status "Service is answering on http://localhost:5000/"
    curl -s http://localhost:5000/pir/status | python3 -c '
import json, sys
s = json.load(sys.stdin)
if s.get("available"):
    print("PIR sensor: OK on GPIO", s.get("pin"), "(", s.get("pin_factory"), ")")
elif s.get("simulation"):
    print("PIR sensor: simulation mode (pir_sensor.simulation_mode=true)")
elif not s.get("enabled"):
    print("PIR sensor: disabled in config.json")
else:
    print("PIR sensor: NOT WORKING ->", s.get("error"))
    print("  Run: sudo systemctl stop family-calendar && .venv/bin/python scripts/pir_smoke_test.py")
' || true
    curl -s http://localhost:5000/api/display | python3 -c '
import json, sys
s = json.load(sys.stdin)
b = s.get("backlight", {})
print("Backlight:", b.get("backend"), "available" if b.get("available") else "(none: browser overlay fallback)")
' || true
  else
    echo -e "${RED}Service is not answering yet.${NC} Check: journalctl -u family-calendar -n 50"
  fi
}

main() {
  section "Family Calendar deployment ($APP_DIR, user $APP_USER)"
  install_system_packages
  setup_permissions
  build_application
  configure_application
  install_service
  install_kiosk
  verify

  section "Done"
  echo "Service:   systemctl status family-calendar    logs: journalctl -u family-calendar -f"
  echo "Kiosk:     starts with the desktop session (or run startup/launch-browser.sh)"
  echo "Health:    http://localhost:5000/health/     PIR: http://localhost:5000/pir/diagnostics"
  echo "Config:    $APP_DIR/config.json"
  echo
  echo "PIR wiring (HC-SR501): VCC -> 5V (pin 2/4), GND -> pin 6, OUT -> GPIO 18 (pin 12)."
  echo "Group membership takes effect after a reboot or re-login."
  read -r -p "Reboot now? (y/n) " -n 1; echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then reboot; fi
}

main "$@"
