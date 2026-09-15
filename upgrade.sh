#!/bin/bash
#
# Family Calendar - upgrade to a release (or the tip of main when there are no
# releases). Used directly from a terminal and, via the
# family-calendar-upgrade@.service unit, by the in-app updater.
#
#   ./upgrade.sh                     interactive: upgrade to the latest release
#   ./upgrade.sh --yes               no prompts
#   ./upgrade.sh --tag v1.2.3        a specific release
#   ./upgrade.sh --status-file F     also write progress as JSON to F
#
# Safety properties, in order:
#   * Everything that can fail without side effects (fetch, locating the tag,
#     checking the working tree) runs BEFORE the service is stopped, so a
#     refusal leaves the display running.
#   * Lockfiles that tools regenerate (uv.lock, frontend/package-lock.json) are
#     restored automatically; any other local change stops the upgrade.
#   * If a step fails after the service was stopped, the previous version is
#     checked out and rebuilt, and the service is started again.
#   * Run with sudo, it re-runs itself as the owner of the checkout, since git
#     refuses to operate on a repository owned by another user.

set -uo pipefail

GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

APP_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SERVICE_NAME="family-calendar"
HEALTH_URL="http://localhost:5000/health/"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Files that package managers rewrite; a difference in them is not a user edit.
REGENERATED_FILES=("uv.lock" "frontend/package-lock.json")

ASSUME_YES=false
TARGET_TAG=""
STATUS_FILE=""

usage() { sed -n '3,12p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    -y|--yes) ASSUME_YES=true ;;
    --tag) TARGET_TAG="${2:-}"; shift ;;
    --status-file) STATUS_FILE="${2:-}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

# --- running as the right user --------------------------------------------

owner_of() { stat -c %U "$1" 2>/dev/null || stat -f %Su "$1"; }

if [ "$(id -u)" -eq 0 ]; then
  OWNER="$(owner_of "$APP_DIR")"
  if [ -n "$OWNER" ] && [ "$OWNER" != "root" ]; then
    echo "Running as root; re-running as $OWNER, who owns $APP_DIR."
    args=()
    $ASSUME_YES && args+=(--yes)
    [ -n "$TARGET_TAG" ] && args+=(--tag "$TARGET_TAG")
    [ -n "$STATUS_FILE" ] && args+=(--status-file "$STATUS_FILE")
    exec sudo -u "$OWNER" -H bash "$0" "${args[@]}"
  fi
fi

BACKUP_DIR="$HOME/.family-calendar-backup"
export PATH="$HOME/.local/bin:$PATH"

# --- output -----------------------------------------------------------------

write_status() {
  [ -n "$STATUS_FILE" ] || return 0
  python3 - "$STATUS_FILE" "$1" "$2" <<'EOF' 2>/dev/null || true
import json, os, sys, time
path, state, message = sys.argv[1:]
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump({"state": state, "message": message, "updated_at": time.time()}, f)
os.replace(tmp, path)
EOF
}

status()  { echo -e "${YELLOW}-->${NC} $1"; write_status running "$1"; }
success() { echo -e "${GREEN}-->${NC} $1"; }
fail() {
  echo -e "${RED}ERROR:${NC} $1" >&2
  write_status error "$1"
  exit 1
}

# --- service control --------------------------------------------------------
#
# Plain systemctl works for the service user through the polkit rule that
# deploy_raspberry_pi.sh installs; sudo is the fallback for older installs.

have_systemd() { command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files "$SERVICE_NAME.service" >/dev/null 2>&1; }

svc() {
  systemctl "$@" "$SERVICE_NAME" 2>/dev/null \
    || sudo -n systemctl "$@" "$SERVICE_NAME" 2>/dev/null \
    || { [ -t 0 ] && sudo systemctl "$@" "$SERVICE_NAME"; }
}

# --- state for rollback -----------------------------------------------------

SERVICE_WAS_RUNNING=false
SERVICE_STOPPED=false
PREVIOUS_REF=""
CHECKED_OUT=false
FINISHED=false

rebuild() {
  (cd "$APP_DIR" && uv sync --frozen --no-dev) || return 1
  (cd "$APP_DIR/frontend" && npm ci --no-audit --no-fund && npm run build) || return 1
}

on_exit() {
  local code=$?
  $FINISHED && return
  if $CHECKED_OUT && [ -n "$PREVIOUS_REF" ]; then
    echo -e "${YELLOW}-->${NC} Rolling back to $PREVIOUS_REF ..."
    git -C "$APP_DIR" checkout -q "$PREVIOUS_REF" && rebuild \
      || echo -e "${RED}Rollback rebuild failed.${NC} Run: git checkout $PREVIOUS_REF && uv sync --frozen --no-dev && (cd frontend && npm ci && npm run build)"
  fi
  # Restart rather than start: if the failure came after the new version was
  # already started, the service must be moved back onto the old code too.
  if $SERVICE_WAS_RUNNING && { $SERVICE_STOPPED || $CHECKED_OUT; }; then
    echo -e "${YELLOW}-->${NC} Restarting $SERVICE_NAME on the previous version ..."
    svc restart || echo -e "${RED}Could not start the service.${NC} Run: sudo systemctl start $SERVICE_NAME"
  fi
  [ "$code" -ne 0 ] && echo -e "${RED}Upgrade did not complete; the previous version is still installed.${NC}"
}
trap on_exit EXIT

# --- steps ------------------------------------------------------------------

check_prerequisites() {
  cd "$APP_DIR" || fail "Cannot enter $APP_DIR"
  [ -d .git ] || fail "Not a git checkout. Upgrades need the app installed with git clone."
  command -v git >/dev/null || fail "git is not installed."
  command -v uv >/dev/null || fail "uv is not installed for $(id -un). Run deploy_raspberry_pi.sh once."
  command -v npm >/dev/null || fail "npm is not installed. Run deploy_raspberry_pi.sh once."
  git status --porcelain >/dev/null 2>&1 \
    || fail "git cannot read this repository as $(id -un): $(git status 2>&1 | head -1)"

  if [ "$(uname -m)" = "aarch64" ]; then
    local missing=()
    command -v swig >/dev/null || missing+=(swig)
    [ -f /usr/include/lgpio.h ] || dpkg -s liblgpio-dev >/dev/null 2>&1 || missing+=(liblgpio-dev)
    if [ ${#missing[@]} -gt 0 ]; then
      status "Installing missing system packages: ${missing[*]}"
      sudo -n apt-get install -y swig liblgpio-dev 2>/dev/null \
        || { [ -t 0 ] && sudo apt-get install -y "${missing[@]}"; } \
        || fail "Missing system packages: ${missing[*]}. Install with: sudo apt-get install -y ${missing[*]}"
    fi
  fi
}

resolve_target() {
  status "Fetching releases ..."
  local out
  out=$(git fetch --tags --force origin 2>&1) || fail "git fetch failed: $out"

  CURRENT_VERSION=$(cat VERSION 2>/dev/null || echo unknown)
  PREVIOUS_REF=$(git symbolic-ref -q --short HEAD || git rev-parse HEAD)

  if [ -z "$TARGET_TAG" ]; then
    TARGET_TAG=$(git tag --list 'v*' --sort=-version:refname | head -1)
  fi

  if [ -n "$TARGET_TAG" ]; then
    git rev-parse -q --verify "refs/tags/$TARGET_TAG" >/dev/null || fail "Release $TARGET_TAG does not exist."
    TARGET_REF="$TARGET_TAG"
    TARGET_VERSION="${TARGET_TAG#v}"
    if [ "$CURRENT_VERSION" = "$TARGET_VERSION" ] && [ "$(git rev-parse HEAD)" = "$(git rev-parse "$TARGET_TAG^{commit}")" ]; then
      success "Already on $TARGET_TAG."
      write_status done "Already up to date ($TARGET_TAG)"
      FINISHED=true
      exit 0
    fi
  else
    TARGET_REF="origin/main"
    TARGET_VERSION="main ($(git rev-parse --short origin/main))"
  fi

  echo -e "${YELLOW}-->${NC} Installed: $CURRENT_VERSION ($PREVIOUS_REF)"
  echo -e "${YELLOW}-->${NC} Target:    $TARGET_VERSION"
}

check_working_tree() {
  local file
  for file in "${REGENERATED_FILES[@]}"; do
    if ! git diff --quiet -- "$file" 2>/dev/null; then
      status "Restoring $file (rewritten by a package manager)"
      git checkout -- "$file"
    fi
  done

  local changed
  changed=$(git status --porcelain --untracked-files=no)
  if [ -n "$changed" ]; then
    echo "$changed" >&2
    fail "Local changes to tracked files would block the upgrade (listed above). Keep them with 'git stash', or discard them with 'git checkout -- <file>', then run the upgrade again."
  fi
}

confirm() {
  $ASSUME_YES && return
  read -r -p "Upgrade to $TARGET_VERSION? (y/n) " -n 1; echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    FINISHED=true
    exit 0
  fi
}

stop_service() {
  if have_systemd && systemctl is-active --quiet "$SERVICE_NAME"; then
    SERVICE_WAS_RUNNING=true
    status "Stopping $SERVICE_NAME ..."
    svc stop || fail "Could not stop $SERVICE_NAME."
    SERVICE_STOPPED=true
  fi
}

backup_user_data() {
  local dest="$BACKUP_DIR/$TIMESTAMP"
  status "Backing up user data to $dest ..."
  mkdir -p "$dest" || fail "Cannot create $dest"

  [ -f config.json ] && cp config.json "$dest/"
  for f in credentials.json calendar_token.json tasks_token.json; do
    [ -f "src/google_integration/$f" ] && cp "src/google_integration/$f" "$dest/"
  done
  # WAL databases: copy the -wal/-shm sidecars too (the service is stopped,
  # so they are normally checkpointed already).
  for db in src/calendar_app/calendar.db src/chores_app/chores.db src/slideshow/slideshow.db; do
    if [ -f "$db" ]; then
      mkdir -p "$dest/$(dirname "$db")"
      for part in "" "-wal" "-shm"; do
        [ -f "$db$part" ] && cp "$db$part" "$dest/$db$part"
      done
    fi
  done
  if [ -d src/static/photos ]; then
    find src/static/photos -maxdepth 1 -type f > "$dest/photo_manifest.txt" 2>/dev/null || true
  fi
  ls -dt "$BACKUP_DIR"/*/ 2>/dev/null | tail -n +6 | xargs rm -rf 2>/dev/null || true
  success "Backup complete"
}

apply_update() {
  status "Checking out $TARGET_VERSION ..."
  local out
  out=$(git checkout -q "$TARGET_REF" 2>&1) || fail "git checkout failed: $out"
  CHECKED_OUT=true
}

install_dependencies() {
  status "Installing Python dependencies ..."
  uv sync --frozen --no-dev || fail "uv sync failed."
  status "Building the frontend ..."
  (cd frontend && npm ci --no-audit --no-fund && npm run build) || fail "Frontend build failed."
}

start_and_verify() {
  if $SERVICE_WAS_RUNNING; then
    status "Starting $SERVICE_NAME ..."
    svc start || fail "Could not start $SERVICE_NAME."
    SERVICE_STOPPED=false
    local i
    for i in $(seq 1 30); do
      if curl -sf --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
        success "Service is healthy"
        return
      fi
      sleep 1
    done
    fail "The service did not answer $HEALTH_URL within 30 seconds after the upgrade."
  else
    echo -e "${YELLOW}-->${NC} The service was not running; start it with: sudo systemctl start $SERVICE_NAME"
  fi
}

main() {
  echo -e "${BLUE}=== Family Calendar Upgrade ===${NC}"
  check_prerequisites
  resolve_target
  check_working_tree
  confirm
  stop_service
  backup_user_data
  apply_update
  install_dependencies
  start_and_verify

  FINISHED=true
  local new_version
  new_version=$(cat VERSION 2>/dev/null || echo unknown)
  write_status done "Upgraded to $new_version"
  success "Upgrade complete: now running $new_version"
  echo -e "Backup: ${BLUE}$BACKUP_DIR/$TIMESTAMP${NC}"
}

# One line, ending in exit: bash reads a script incrementally, and the checkout
# above can replace this very file while it runs. Nothing after this line is
# ever read.
main; exit $?
