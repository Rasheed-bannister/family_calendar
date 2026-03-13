#!/bin/bash

# Family Calendar - Upgrade Script
# Safely upgrades the application to the latest release while preserving user data.

set -e

# ANSI color codes
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

APP_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BACKUP_DIR="$HOME/.family-calendar-backup"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

status() { echo -e "${YELLOW}-->${NC} $1"; }
success() { echo -e "${GREEN}-->${NC} $1"; }
error() { echo -e "${RED}ERROR:${NC} $1"; exit 1; }

# Check we're in a git repo
check_prerequisites() {
    cd "$APP_DIR"
    [ -d ".git" ] || error "Not a git repository. Upgrade requires the app to be installed via git clone."
    command -v git >/dev/null || error "git is not installed."
}

# Show current and available versions
show_versions() {
    CURRENT_VERSION=$(cat "$APP_DIR/VERSION" 2>/dev/null || echo "unknown")
    status "Current version: $CURRENT_VERSION"

    # Fetch latest tags from remote
    git fetch --tags --quiet 2>/dev/null || error "Could not reach GitHub. Check your internet connection."

    LATEST_TAG=$(git tag --sort=-version:refname | head -1)
    if [ -z "$LATEST_TAG" ]; then
        success "No releases found. You're running from the development branch."
        echo ""
        read -p "Pull latest changes from main? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            UPGRADE_MODE="branch"
        else
            exit 0
        fi
    else
        LATEST_VERSION="${LATEST_TAG#v}"
        status "Latest release: $LATEST_VERSION ($LATEST_TAG)"

        if [ "$CURRENT_VERSION" = "$LATEST_VERSION" ]; then
            success "Already up to date!"
            exit 0
        fi

        echo ""
        read -p "Upgrade to $LATEST_TAG? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            UPGRADE_MODE="tag"
            UPGRADE_TARGET="$LATEST_TAG"
        else
            exit 0
        fi
    fi
}

# Backup user data (insurance policy — git won't touch gitignored files)
backup_user_data() {
    status "Backing up user data to $BACKUP_DIR/$TIMESTAMP ..."
    mkdir -p "$BACKUP_DIR/$TIMESTAMP"

    # Config
    [ -f "$APP_DIR/config.json" ] && cp "$APP_DIR/config.json" "$BACKUP_DIR/$TIMESTAMP/"

    # Google credentials and tokens
    for f in credentials.json calendar_token.json tasks_token.json; do
        [ -f "$APP_DIR/src/google_integration/$f" ] && cp "$APP_DIR/src/google_integration/$f" "$BACKUP_DIR/$TIMESTAMP/"
    done

    # Databases
    for db in src/calendar_app/calendar.db src/chores_app/chores.db src/slideshow/slideshow.db; do
        if [ -f "$APP_DIR/$db" ]; then
            mkdir -p "$BACKUP_DIR/$TIMESTAMP/$(dirname "$db")"
            cp "$APP_DIR/$db" "$BACKUP_DIR/$TIMESTAMP/$db"
        fi
    done

    # Photo manifest (not the photos themselves — too large)
    if [ -d "$APP_DIR/src/static/photos" ]; then
        find "$APP_DIR/src/static/photos" -type f \( -name "*.jpg" -o -name "*.jpeg" -o -name "*.png" -o -name "*.webp" -o -name "*.gif" \) | \
            sed "s|$APP_DIR/||" > "$BACKUP_DIR/$TIMESTAMP/photo_manifest.txt" 2>/dev/null || true
        PHOTO_COUNT=$(wc -l < "$BACKUP_DIR/$TIMESTAMP/photo_manifest.txt" 2>/dev/null || echo "0")
        status "Photo manifest saved ($PHOTO_COUNT photos tracked, files untouched)"
    fi

    # Keep only last 5 backups
    ls -dt "$BACKUP_DIR"/*/ 2>/dev/null | tail -n +6 | xargs rm -rf 2>/dev/null || true

    success "Backup complete"
}

# Stop the running service
stop_service() {
    if systemctl is-active --quiet family-calendar 2>/dev/null; then
        status "Stopping family-calendar service..."
        sudo systemctl stop family-calendar
        SERVICE_WAS_RUNNING=true
    else
        SERVICE_WAS_RUNNING=false
    fi
}

# Pull the update
apply_update() {
    cd "$APP_DIR"

    if [ "$UPGRADE_MODE" = "tag" ]; then
        status "Checking out $UPGRADE_TARGET ..."
        git checkout "$UPGRADE_TARGET"
    else
        status "Pulling latest changes from main ..."
        git pull origin main
    fi
}

# Reinstall dependencies
install_dependencies() {
    status "Installing dependencies..."
    cd "$APP_DIR"

    if command -v uv >/dev/null; then
        if [ ! -d ".venv" ]; then
            uv venv
        fi
        uv pip install -e .
    elif [ -f ".venv/bin/pip" ]; then
        source .venv/bin/activate
        pip install -e .
    else
        error "No package manager found. Install uv (https://docs.astral.sh/uv/) or create a virtualenv."
    fi

    success "Dependencies installed"
}

# Restart the service
restart_service() {
    if [ "$SERVICE_WAS_RUNNING" = true ]; then
        status "Restarting family-calendar service..."
        sudo systemctl start family-calendar

        # Wait for health check
        sleep 3
        if curl -sf http://localhost:5000/health/ > /dev/null 2>&1; then
            success "Service restarted and healthy"
        else
            echo -e "${YELLOW}WARNING:${NC} Service started but health check not responding yet. Give it a moment."
        fi
    else
        status "Service was not running. Start it with: sudo systemctl start family-calendar"
    fi
}

# Main
main() {
    echo -e "${BLUE}=== Family Calendar Upgrade ===${NC}"
    echo ""

    check_prerequisites
    show_versions
    backup_user_data
    stop_service
    apply_update
    install_dependencies
    restart_service

    echo ""
    NEW_VERSION=$(cat "$APP_DIR/VERSION" 2>/dev/null || echo "unknown")
    success "Upgrade complete! Now running version $NEW_VERSION"
    echo -e "Backup saved at: ${BLUE}$BACKUP_DIR/$TIMESTAMP${NC}"
}

main
