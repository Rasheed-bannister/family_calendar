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

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Configuration variables - modify these as needed
APP_DIR="${SCRIPT_DIR}"
REPO_URL="https://github.com/Rasheed-bannister/family_calendar.git"
MIN_PYTHON_VERSION="3.11" # Minimum Python version - more flexible than requiring 3.13 exactly

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
    error "Python 3 is not installed. Please install Python ${MIN_PYTHON_VERSION} or higher."
  fi
  
  local version
  version=$($python_cmd --version | cut -d " " -f 2)
  local major_version=$(echo "$version" | cut -d. -f1)
  local minor_version=$(echo "$version" | cut -d. -f2)
  
  if [ "$major_version" -lt 3 ] || ([ "$major_version" -eq 3 ] && [ "$minor_version" -lt 11 ]); then
    error "Python ${MIN_PYTHON_VERSION} or higher is required. Found: $version"
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
    python3-rpi.gpio \
    openssl \
    || error "Failed to install required packages"
    
  status "System dependencies installed successfully"
}

# Configure GPIO permissions for PIR sensor
setup_gpio_permissions() {
  section "Configuring GPIO Permissions for PIR Sensor"
  
  local username=$(logname)
  
  status "Adding user to gpio group..."
  usermod -a -G gpio $username || error "Failed to add user to gpio group"
  
  status "Setting GPIO permissions..."
  if [ -e /dev/gpiomem ]; then
    chmod 666 /dev/gpiomem || error "Failed to set GPIO permissions"
    status "GPIO permissions configured successfully"
  else
    status "GPIO device not found, skipping permissions setup"
  fi
  
  status "PIR sensor GPIO configuration completed"
}

# Set up the Family Calendar application
setup_application() {
  section "Setting Up Family Calendar Application"
  
  status "Using application directory: $APP_DIR"
  cd "$APP_DIR"
  
  # Check if we're in a git repo and update if possible
  if [ -d ".git" ]; then
    status "Updating repository..."
    git pull || status "Unable to update repository, continuing with current version"
  fi
  
  # Get the current user for proper permissions
  local username=$(logname)
  local user_home=$(eval echo ~$username)
    
  status "Creating Python virtual environment..."
  python3 -m venv .venv || error "Failed to create virtual environment"
  
  # Fix permissions on the virtual environment
  chown -R $username:$username .venv
  
  # Update pyproject.toml to be compatible with available Python version
  if [ -f "pyproject.toml" ]; then
    status "Updating Python version requirement in pyproject.toml..."
    sed -i 's/requires-python = ">=3.13"/requires-python = ">=3.11"/' pyproject.toml || status "Could not update Python version in pyproject.toml, continuing anyway"
  fi
  
  status "Installing Python dependencies..."
  source .venv/bin/activate
  
  # Use pip directly to avoid UV issues
  pip install --upgrade pip
  pip install -e . || error "Failed to install Python dependencies"
  
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

# Configure application settings
configure_application_settings() {
  section "Configuring Application Settings"
  
  echo "Please provide your family information and location for the calendar."
  echo "This will be stored in the application configuration file."
  echo "You can find your coordinates using https://www.latlong.net/"
  echo
  
  FAMILY_NAME=$(ask_with_default "Enter your family name (e.g., Smith Family)" "Family")
  LATITUDE=$(ask_with_default "Enter your latitude" "$DEFAULT_LATITUDE")
  LONGITUDE=$(ask_with_default "Enter your longitude" "$DEFAULT_LONGITUDE")
  TIMEZONE=$(ask_with_default "Enter your timezone (e.g., America/New_York)" "$DEFAULT_TIMEZONE")

  status "Creating application configuration file..."
  
  # Create config.json with proper settings for production deployment
  cat > "$APP_DIR/config.json" << EOF
{
  "app": {
    "debug": false,
    "host": "0.0.0.0",
    "port": 5000,
    "secret_key": "$(openssl rand -hex 32)",
    "use_reloader": false,
    "environment": "production",
    "family_name": "$FAMILY_NAME"
  },
  "weather": {
    "latitude": $LATITUDE,
    "longitude": $LONGITUDE,
    "timezone": "$TIMEZONE",
    "cache_duration": 600,
    "offline_fallback": true
  },
  "pir_sensor": {
    "enabled": true,
    "gpio_pin": 18,
    "debounce_time": 2.0,
    "simulation_mode": false
  },
  "inactivity": {
    "day_timeout_minutes": 60,
    "night_timeout_seconds": 5,
    "day_brightness_reduction": 0.6,
    "night_brightness_reduction": 0.2,
    "night_start_hour": 21,
    "night_end_hour": 6,
    "slideshow_delay_seconds": 5
  },
  "google": {
    "sync_interval_minutes": 3,
    "max_retry_attempts": 3,
    "offline_mode_enabled": true
  },
  "ui": {
    "show_loading_indicators": false,
    "show_pir_feedback": false,
    "enhanced_virtual_keyboard": true,
    "touch_optimized": true,
    "animation_duration_ms": 300
  },
  "paths": {
    "photos_dir": "src/static/photos",
    "credentials_dir": "src/google_integration"
  },
  "logging": {
    "level": "WARN",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "file": "calendar.log",
    "max_bytes": 10485760,
    "backup_count": 5
  }
}
EOF
  
  # Ensure proper ownership of config file
  local username=$(logname)
  chown $username:$username "$APP_DIR/config.json"
  
  status "Application configuration created successfully"
}

# Create autostart entry
setup_autostart() {
  section "Setting Up Autostart"
  
  local username=$(logname)
  local user_home=$(eval echo ~$username)
  local autostart_dir="$user_home/.config/autostart"
  
  status "Creating launcher scripts..."
  
  # Ensure startup directory exists
  mkdir -p "$APP_DIR/startup"
  
  # Create launch-calendar.sh
  cat > "$APP_DIR/startup/launch-calendar.sh" << EOF
#!/bin/bash
# Start the Flask server in the background
cd $APP_DIR

# Ensure we have a virtual environment
if [ ! -f .venv/bin/activate ]; then
  echo "Error: Virtual environment not found"
  exit 1
fi

source .venv/bin/activate

# Wait for any system startup processes to complete
sleep 3

# Check if config file exists
if [ ! -f config.json ]; then
  echo "Error: Configuration file config.json not found"
  exit 1
fi

# Start the application with proper module import
echo "Starting Family Calendar application..."
python -m src.main &

# Save the PID for potential later use
echo \$! > /tmp/calendar-server.pid
echo "Calendar server started with PID: \$(cat /tmp/calendar-server.pid)"
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
  
  # Ensure the user has ownership of the startup scripts
  chown -R $username:$username "$APP_DIR/startup/"
  
  # Ensure the entire app directory is owned by the user
  chown -R $username:$username "$APP_DIR"
  
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
  # Test that configuration loads properly and databases are initialized
  su $username -c "cd $APP_DIR && source .venv/bin/activate && python -c 'from src.config import get_config; config = get_config(); print(\"Configuration loaded successfully\")'" 
  
  status "Testing PIR sensor connectivity..."
  su $username -c "cd $APP_DIR && source .venv/bin/activate && python -c 'from src.pir_sensor.sensor import initialize_pir_sensor; result = initialize_pir_sensor(); print(\"PIR sensor initialization:\", \"Success\" if result else \"Failed (check hardware connection)\")'"
  
  status "Initial setup completed"
  echo -e "${YELLOW}NOTE:${NC} When the application starts for the first time, you will need to authorize it with your Google account."
  echo -e "${YELLOW}CONFIG:${NC} Application settings can be modified in $APP_DIR/config.json"
  echo -e "${YELLOW}FAMILY NAME:${NC} The family name '$FAMILY_NAME' will be displayed in the calendar header"
  echo -e "${YELLOW}PIR SENSOR:${NC} Connect PIR sensor OUT pin to GPIO 18 (Pin 12) for motion detection."
}

# Setup health monitoring and systemd service
setup_health_monitoring() {
  section "Setting Up Health Monitoring"
  
  local username=$(logname)
  
  status "Installing systemd service..."
  
  # Update service file paths
  sed -i "s|/home/pi/family_calendar|$APP_DIR|g" "$APP_DIR/startup/family-calendar.service"
  sed -i "s|User=pi|User=$username|g" "$APP_DIR/startup/family-calendar.service"
  sed -i "s|Group=pi|Group=$username|g" "$APP_DIR/startup/family-calendar.service"
  
  # Install systemd service
  cp "$APP_DIR/startup/family-calendar.service" /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable family-calendar.service
  
  status "Setting up health monitor script..."
  
  # Update health monitor script paths
  sed -i "s|/home/pi/family_calendar|$APP_DIR|g" "$APP_DIR/startup/health-monitor.sh"
  
  # Make health monitor script executable
  chmod +x "$APP_DIR/startup/health-monitor.sh"
  
  # Create log directory
  mkdir -p /var/log
  touch /var/log/family-calendar-monitor.log
  chown $username:$username /var/log/family-calendar-monitor.log
  
  # Create systemd service for health monitor
  cat > /etc/systemd/system/family-calendar-monitor.service << EOF
[Unit]
Description=Family Calendar Health Monitor
After=family-calendar.service
Requires=family-calendar.service

[Service]
Type=simple
User=$username
Group=$username
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/startup/health-monitor.sh
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable family-calendar-monitor.service
  
  status "Health monitoring setup completed"
  echo -e "${YELLOW}HEALTH:${NC} Health endpoint available at http://localhost:5000/health/"
  echo -e "${YELLOW}MONITORING:${NC} Automatic restart enabled with health monitoring"
}

# Main deployment process
main() {
  section "Family Calendar & Photo Slideshow - Deployment Script"
  
  status "Deploying from: $APP_DIR"
  
  check_sudo
  install_system_dependencies
  setup_gpio_permissions
  setup_application
  configure_google_api
  configure_application_settings
  setup_autostart
  configure_screen
  setup_health_monitoring
  run_initial_setup
  
  section "Deployment Completed Successfully"
  echo -e "${GREEN}Family Calendar & Photo Slideshow has been successfully deployed!${NC}"
  echo -e "The application will start automatically on next boot."
  echo -e "To start it manually, run: ${YELLOW}bash $APP_DIR/startup/launch.sh${NC}"
  echo ""
  echo -e "${BLUE}PIR Sensor Setup:${NC}"
  echo -e "• Connect PIR sensor VCC to Pin 2 or 4 (5V)"
  echo -e "• Connect PIR sensor GND to Pin 6 (Ground)"
  echo -e "• Connect PIR sensor OUT to Pin 12 (GPIO 18)"
  echo -e "• Position sensor to detect motion in desired area"
  echo ""
  echo -e "${BLUE}Features Available:${NC}"
  echo -e "• Touch-optimized calendar and task management"
  echo -e "• Motion-activated display wake-up"
  echo -e "• Google Calendar and Tasks integration"
  echo -e "• Weather display and photo slideshow"
  echo -e "• Configurable logging and debug settings"
  echo ""
  echo -e "${BLUE}Configuration:${NC}"
  echo -e "• Application settings: $APP_DIR/config.json"
  echo -e "• Application logs: $APP_DIR/calendar.log"
  echo -e "• Health monitor logs: /var/log/family-calendar-monitor.log"
  echo -e "• Logging level set to WARN for production use"
  echo ""
  echo -e "${BLUE}Health Monitoring:${NC}"
  echo -e "• Health endpoint: http://localhost:5000/health/"
  echo -e "• Detailed health: http://localhost:5000/health/detailed"
  echo -e "• System resources: http://localhost:5000/health/system"
  echo -e "• Automatic restart on critical errors enabled"
  echo -e "• Service management: systemctl status family-calendar"
  
  read -p "Would you like to reboot now to apply all changes? (y/n) " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    status "Rebooting system..."
    reboot
  fi
}

# Run the deployment process
main