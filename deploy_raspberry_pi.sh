#!/bin/bash

# Family Calendar & Photo Slideshow - Raspberry Pi Deployment Script
# This script automates the installation and setup process for the Family Calendar
# application on a Raspberry Pi with a touchscreen display.

set -e  # Exit immediately if a command exits with a non-zero status

# ANSI color codes for better readability
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuration variables - modify these as needed
APP_DIR="$HOME/family-calendar"
REPO_URL="https://github.com/Rasheed-bannister/family_calendar.git"
PYTHON_VERSION="3.13" # Matches the requirement in pyproject.toml

# Weather configuration defaults - can be modified during installation
DEFAULT_LATITUDE="40.759010"
DEFAULT_LONGITUDE="-73.984474"
DEFAULT_TIMEZONE="America/New_York"

# Print section header
section() {
  echo -e "\n${BLUE}===${NC} ${GREEN}$1${NC} ${BLUE}===${NC}\n"
}

# Print status message
status() {
  echo -e "${YELLOW}-->${NC} $1"
}

# Print error message and exit
error() {
  echo -e "${RED}ERROR:${NC} $1"
  exit 1
}

# Ask for user input with a default value
ask_with_default() {
  local prompt="$1"
  local default="$2"
  local result=""

  read -p "$prompt [$default]: " result
  echo "${result:-$default}"
}

# Check for sudo privileges
check_sudo() {
  if [ "$(id -u)" -ne 0 ]; then
    error "This script must be run with sudo privileges. Please run: sudo $0"
  fi
}

# Check for minimum Python version
check_python_version() {
  local python_cmd
  if command -v python3 >/dev/null; then
    python_cmd="python3"
  else
    error "Python 3 is not installed. Please install Python ${PYTHON_VERSION} or higher."
  fi
  
  local version
  version=$($python_cmd --version | cut -d " " -f 2)
  local major_version=$(echo "$version" | cut -d. -f1)
  local minor_version=$(echo "$version" | cut -d. -f2)
  
  if [ "$major_version" -lt 3 ] || ([ "$major_version" -eq 3 ] && [ "$minor_version" -lt 11 ]); then
    error "Python ${PYTHON_VERSION} or higher is required. Found: $version"
  fi
  
  status "Python version check passed: $version"
}

# Install system dependencies
install_system_dependencies() {
  section "Installing System Dependencies"
  
  status "Updating package lists..."
  apt-get update || error "Failed to update package lists"
  
  status "Installing required packages..."
  apt-get install -y \
    git \
    python3-venv \
    curl \
    ca-certificates \
    xscreensaver \
    xinput-calibrator \
    chromium-browser \
    || error "Failed to install required packages"
    
  status "System dependencies installed successfully"
}

# Set up the Family Calendar application
setup_application() {
  section "Setting Up Family Calendar Application"
  
  if [ -d "$APP_DIR" ]; then
    status "Application directory already exists. Updating..."
    cd "$APP_DIR"
    git pull || error "Failed to update repository"
  else
    status "Cloning repository..."
    git clone "$REPO_URL" "$APP_DIR" || error "Failed to clone repository"
    cd "$APP_DIR"
  fi
  
  status "Installing UV package manager..."
 curl -LsSf https://astral.sh/uv/install.sh | sh || error "Failed to install UV"
 source $HOME/.local/bin/env
  
  status "Creating Python virtual environment..."
  uv venv .venv || error "Failed to create virtual environment"
  
  status "Installing Python dependencies..."
  source .venv/bin/activate
  uv pip sync || error "Failed to install Python dependencies"
  
  status "Application setup completed successfully"
}

# Configure Google API credentials
configure_google_api() {
  section "Configuring Google API"
  
  if [ ! -f "$APP_DIR/src/google_integration/credentials.json" ]; then
    echo -e "${YELLOW}NOTICE:${NC} Google API credentials are required for calendar and tasks integration."
    echo "Please follow these steps:"
    echo "1. Go to https://console.cloud.google.com/"
    echo "2. Create a new project"
    echo "3. Enable the Google Calendar API and Google Tasks API"
    echo "4. Create OAuth credentials (Desktop application type)"
    echo "5. Download the credentials.json file"
    echo "6. Place the file in $APP_DIR/src/google_integration/"
    
    read -p "Press Enter to continue after you've added the credentials.json file..."
  else
    status "Google API credentials file found"
  fi
}

# Configure weather settings
configure_weather_settings() {
  section "Configuring Weather Settings"
  
  echo "Please provide your location information for weather forecasting."
  echo "This will be stored in environment variables for the application."
  echo "You can find your coordinates using https://www.latlong.net/"
  echo
  
  LATITUDE=$(ask_with_default "Enter your latitude" "$DEFAULT_LATITUDE")
  LONGITUDE=$(ask_with_default "Enter your longitude" "$DEFAULT_LONGITUDE")
  TIMEZONE=$(ask_with_default "Enter your timezone" "$DEFAULT_TIMEZONE")
  
  status "Setting up environment variables..."
  
  local env_file="/etc/profile.d/family-calendar-env.sh"
  cat > "$env_file" << EOF
#!/bin/bash
# Environment variables for Family Calendar & Photo Slideshow
export CALENDAR_WEATHER_LATITUDE="$LATITUDE"
export CALENDAR_WEATHER_LONGITUDE="$LONGITUDE"
export CALENDAR_TIMEZONE="$TIMEZONE"
EOF

  chmod +x "$env_file"
  
  # Also add to the current user's .bashrc for immediate use
  local username=$(logname)
  local user_home=$(eval echo ~$username)
  
  if ! grep -q "CALENDAR_WEATHER_LATITUDE" "$user_home/.bashrc"; then
    cat >> "$user_home/.bashrc" << EOF

# Family Calendar & Photo Slideshow environment variables
export CALENDAR_WEATHER_LATITUDE="$LATITUDE"
export CALENDAR_WEATHER_LONGITUDE="$LONGITUDE"
export CALENDAR_TIMEZONE="$TIMEZONE"
EOF
  fi
  
  # Export variables for immediate use in this session
  export CALENDAR_WEATHER_LATITUDE="$LATITUDE"
  export CALENDAR_WEATHER_LONGITUDE="$LONGITUDE"
  export CALENDAR_TIMEZONE="$TIMEZONE"
  
  status "Weather settings configured successfully"
}

# Create autostart entry
setup_autostart() {
  section "Setting Up Autostart"
  
  local username=$(logname)
  local user_home=$(eval echo ~$username)
  local autostart_dir="$user_home/.config/autostart"
  
  status "Creating launcher scripts..."
  
  # Create launch-calendar.sh
  cat > "$APP_DIR/startup/launch-calendar.sh" << EOF
#!/bin/bash
# Load environment variables if they exist
if [ -f /etc/profile.d/family-calendar-env.sh ]; then
  source /etc/profile.d/family-calendar-env.sh
fi

# Start the Flask server in the background
cd $APP_DIR
source .venv/bin/activate
python -m src.main &
EOF
  
  # Create launch-browser.sh
  cat > "$APP_DIR/startup/launch-browser.sh" << EOF
#!/bin/bash
# Launch Chromium in kiosk mode
chromium-browser --kiosk --incognito --disable-pinch --overscroll-history-navigation=0 http://localhost:5000
EOF

  # Create launch-screensaver.sh (empty for now but included for completeness)
  cat > "$APP_DIR/startup/launch-screensaver.sh" << EOF
#!/bin/bash
# Placeholder for screensaver settings
EOF

  # Create main launch script
  cat > "$APP_DIR/startup/launch.sh" << EOF
#!/bin/bash

cd $APP_DIR/startup

./launch-calendar.sh
./launch-screensaver.sh
sleep 5

./launch-browser.sh
EOF

  # Make all scripts executable
  chmod +x "$APP_DIR/startup/launch-calendar.sh"
  chmod +x "$APP_DIR/startup/launch-browser.sh"
  chmod +x "$APP_DIR/startup/launch-screensaver.sh"
  chmod +x "$APP_DIR/startup/launch.sh"
  chown $username:$username "$APP_DIR/startup/"*.sh
  
  status "Creating autostart entry..."
  mkdir -p "$autostart_dir"
  cat > "$autostart_dir/calendar-kiosk.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Family Calendar Kiosk
Exec=/bin/bash $APP_DIR/startup/launch.sh
X-GNOME-Autostart-enabled=true
EOF
  
  chown -R $username:$username "$autostart_dir"
  
  status "Autostart configuration completed"
}

# Configure screen settings
configure_screen() {
  section "Configuring Screen Settings"
  
  status "Disabling screen blanking..."
  cat > /etc/xdg/lxsession/LXDE-pi/autostart << EOF
@lxpanel --profile LXDE-pi
@pcmanfm --desktop --profile LXDE-pi
@xset s off
@xset -dpms
@xset s noblank
EOF
  
  status "Screen configuration completed"
}

# Run initial application setup
run_initial_setup() {
  section "Running Initial Application Setup"
  
  local username=$(logname)
  
  status "Initializing application databases..."
  cd "$APP_DIR"
  # The databases are initialized automatically when main.py runs
  su $username -c "cd $APP_DIR && source .venv/bin/activate && python -m src.main --setup-only" 
  
  status "Initial setup completed"
  echo -e "${YELLOW}NOTE:${NC} When the application starts for the first time, you will need to authorize it with your Google account."
}

# Main deployment process
main() {
  section "Family Calendar & Photo Slideshow - Deployment Script"
  
  check_sudo
  install_system_dependencies
  setup_application
  configure_google_api
  configure_weather_settings
  setup_autostart
  configure_screen
  run_initial_setup
  
  section "Deployment Completed Successfully"
  echo -e "${GREEN}Family Calendar & Photo Slideshow has been successfully deployed!${NC}"
  echo -e "The application will start automatically on next boot."
  echo -e "To start it manually, run: ${YELLOW}bash $APP_DIR/startup/launch.sh${NC}"
  
  read -p "Would you like to reboot now to apply all changes? (y/n) " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    status "Rebooting system..."
    reboot
  fi
}

# Run the deployment process
main