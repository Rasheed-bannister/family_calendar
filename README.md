# Family Calendar & Photo Slideshow

A wall-mounted family calendar and photo slideshow application designed to run on a Raspberry Pi with a touchscreen monitor, built with Flask and JavaScript.

![main view](main_view.png)
![modal view](modal_view.png)

## Description

This open source project provides families with an interactive digital calendar and photo slideshow system that can be mounted in common areas of your home. It integrates with Google Calendar and Google Tasks, displays weather information, and transforms into a photo slideshow during periods of inactivity.

## Features

### Calendar Functionality
- **Interactive Monthly Calendar**: Displays a full month with color-coded events on the left side of the screen
- **Daily Schedule View**: Shows hourly breakdown of the current day's activities on the right side
- **Google Calendar Integration**: 
  - Automatic background syncing of calendar events
  - Support for multiple calendars with color coding
  - Proper handling of all-day events and recurring events
- **Google Tasks Integration**:
  - Display of tasks/chores from Google Tasks
  - Background synchronization to keep tasks up to date
- **Smart Activity Detection**:
  - Detects user interaction via touch, mouse, and keyboard
  - **PIR Motion Sensor Integration**: Automatically detects motion and wakes display
  - Automatically switches between active and inactive modes
  - Different timeout settings for day and night

### Motion Detection & Power Management
- **PIR Sensor Integration**:
  - Connects to GPIO pin 18 on Raspberry Pi 5
  - Real-time motion detection with configurable sensitivity
  - Automatic display wake-up when people approach
  - Debounce protection to prevent false triggers
- **Intelligent Power Saving**:
  - Automatic dimming during inactivity periods
  - PIR sensor disrupts inactivity timers instantly
  - Different brightness levels for day and night modes
  - Seamless transition between sleep and active states

### Weather Integration
- **Current Weather Display**: 
  - Shows current temperature and conditions
  - Displays appropriate weather icons
- **Weather Forecast**: 
  - Multi-day weather forecast
  - Regular background updates

### Photo Slideshow Functionality
- **Adaptive Inactivity Modes**:
  - Day mode with reduced brightness
  - Night mode with further reduced brightness
  - Long inactivity mode that activates the slideshow
- **Smart Photo Management**:
  - Automatic detection and indexing of photos in the photos directory
  - Random photo selection for slideshow variety
  - SQLite database tracking for efficient photo management
- **Smooth Transitions**: Fade transitions between calendar view and photos

### System Features
- **Flask Web Application**: 
  - Python backend with Flask routing
  - Modular JavaScript frontend
- **Responsive Design**: Adapts to different monitor sizes and is optimized for touchscreen use
- **True Touchscreen Experience**: 
  - Hidden mouse cursor for touch-only interaction
  - Virtual keyboard support for text input
  - Touch-optimized UI components
- **Hardware Integration**:
  - PIR motion sensor support via GPIO
  - Automatic fallback to simulation mode for development
  - Real-time sensor communication via Server-Sent Events
- **Energy Efficiency**:
  - Power-saving modes during periods of inactivity
  - Motion-activated display wake-up
  - Different brightness levels based on time of day
- **Database-Backed**: SQLite databases for efficient data storage and retrieval
- **Background Processing**: 
  - Multi-threaded background tasks for syncing services
  - Thread-safe operations with proper locking mechanisms

## Technical Architecture

The application is built using the following technologies:

- **Backend**:
  - Python 3.13+
  - Flask web framework
  - SQLite databases
  - Threading for background operations
  - Google API clients

- **Frontend**:
  - HTML/CSS with responsive design
  - Modular JavaScript (ES6)
  - Component-based architecture
  
- **Modules**:
  - `calendar_app`: Core calendar functionality and database
  - `google_integration`: Google Calendar and Tasks API integration
  - `slideshow`: Photo management and display
  - `weather_integration`: Weather data fetching and formatting
  - `pir_sensor`: PIR motion sensor integration and GPIO control

## Installation

### Prerequisites
- Raspberry Pi 5 (4GB+ RAM recommended for optimal performance)
- PIR motion sensor (HC-SR501 or compatible)
- Touchscreen monitor with appropriate cables
- SD card (32GB+ recommended)
- Power supply for Raspberry Pi
- Internet connection
- Python 3.13+
- Google Cloud OAuth credentials

### Hardware Setup
1. **Connect PIR Sensor**:
   - Connect VCC to 5V pin (Pin 2 or 4)
   - Connect GND to Ground pin (Pin 6, 9, 14, 20, 25, 30, 34, or 39)
   - Connect OUT to GPIO 18 (Pin 12)
   - Ensure PIR sensor is positioned to detect motion in desired area

2. **Touchscreen Setup**:
   - Connect touchscreen via HDMI and USB
   - Ensure proper power supply for both Pi and display

### Automated Installation (Recommended)

We provide a deployment script that automates the installation and setup process:

1. **Download the script**:
   ```bash
   curl -O https://raw.githubusercontent.com/Rasheed-bannister/family_calendar/main/deploy_raspberry_pi.sh
   chmod +x deploy_raspberry_pi.sh
   ```

2. **Run the script with sudo**:
   ```bash
   sudo ./deploy_raspberry_pi.sh
   ```

The script will:
- Install all required dependencies
- Clone the repository
- Set up a Python virtual environment
- Configure autostart settings
- Set up the display for optimal performance
- Configure GPIO permissions for PIR sensor
- Guide you through adding Google API credentials
- Test PIR sensor functionality
- Offer to reboot when complete

### Manual Installation

If you prefer to install manually, follow these steps:

1. **Set up your Raspberry Pi**:
   ```bash
   # Download and install Raspberry Pi OS (64-bit)
   # Follow instructions at https://www.raspberrypi.org/software/
   ```

2. **Clone the repository**:
   ```bash
   git clone https://github.com/Rasheed-bannister/family_calendar.git
   cd family-calendar
   ```

3. **Install dependencies**:
   ```bash
   # Install UV package manager
   curl -sSf https://install.python-poetry.org | python3 -
   
   # Install project dependencies
   uv venv
   source .venv/bin/activate
   uv pip install -e .
   ```

4. **Set up Google API credentials**:
   1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
   2. Create a new project
   3. Enable the Google Calendar API and Google Tasks API
   4. Create OAuth credentials (Desktop application type)
   5. Download the credentials.json file
   6. Place the file in the `src/google_integration/` directory

5. **Initialize the application**:
   ```bash
   # Run the application once to initialize databases and authenticate with Google
   # This will prompt you to authorize the application with your Google account
   uv run src/main.py
   ```

### Deploying on Raspberry Pi

1. **Configure GPIO permissions**:
   ```bash
   # Add user to gpio group for PIR sensor access
   sudo usermod -a -G gpio $USER
   
   # Set up GPIO permissions
   sudo chmod 666 /dev/gpiomem
   ```

2. **Test PIR sensor**:
   ```bash
   # Test PIR sensor connectivity
   cd family-calendar
   source .venv/bin/activate
   python -c "from src.pir_sensor.sensor import PIRSensor; sensor = PIRSensor(); print('GPIO available:', sensor.gpio_available)"
   ```

3. **Enable auto-start on boot**:
   ```bash
   mkdir -p ~/.config/autostart
   cat > ~/.config/autostart/calendar.desktop << EOF
   [Desktop Entry]
   Type=Application
   Name=Family Calendar
   Exec=/bin/bash -c "cd /path/to/family-calendar && source .venv/bin/activate && python src/main.py"
   X-GNOME-Autostart-enabled=true
   EOF
   ```

2. **Configure screen settings**:
   ```bash
   # Prevent screen from sleeping
   sudo apt-get install xscreensaver
   xscreensaver-command -exit
   ```

3. **Setup touchscreen calibration**:
   ```bash
   sudo apt-get install xinput-calibrator
   xinput_calibrator
   # Follow on-screen instructions
   ```

4. **Configure browser in kiosk mode**:
   ```bash
   # Install Chromium browser if not already installed
   sudo apt-get install chromium-browser
   
   # Create a script to launch in kiosk mode
   cat > ~/launch-calendar.sh << EOF
   #!/bin/bash
   # Start the Flask server in the background
   cd /path/to/family-calendar
   source .venv/bin/activate
   python src/main.py &
   
   # Wait for server to start
   sleep 5
   
   # Launch Chromium in kiosk mode
   chromium-browser --kiosk --incognito --disable-pinch --overscroll-history-navigation=0 http://localhost:5000
   EOF
   
   chmod +x ~/launch-calendar.sh
   ```

5. **Add the script to autostart**:
   ```bash
   cat > ~/.config/autostart/calendar-kiosk.desktop << EOF
   [Desktop Entry]
   Type=Application
   Name=Calendar Kiosk
   Exec=/bin/bash /home/pi/launch-calendar.sh
   X-GNOME-Autostart-enabled=true
   EOF
   ```

## Configuration

The application behavior can be modified by editing various JavaScript and Python files:

### PIR Sensor Settings
The PIR sensor can be configured in `src/main.py`:
```python
# GPIO pin for PIR sensor (default: 18)
pir_sensor = initialize_pir_sensor(pin=18, callback=on_motion_detected)

# Debounce time to prevent false triggers (default: 2.0 seconds)
# Adjust based on your PIR sensor sensitivity
```

### Inactivity Settings
In `src/static/js/app.js`, adjust these constants:
```javascript
// Time in milliseconds before inactivity modes trigger
const DAY_INACTIVITY_TIMEOUT = 3600000;  // 1 hour for daytime
const NIGHT_INACTIVITY_TIMEOUT = 5000;   // 5 seconds for nighttime
const SLIDESHOW_START_DELAY = 5000;      // 5 seconds after entering inactivity

// PIR sensor will instantly wake display regardless of these timeouts
```

### Weather Location Settings
The application uses environment variables to configure weather location settings:

```bash
# Set your location coordinates (find them at https://www.latlong.net/)
export CALENDAR_WEATHER_LATITUDE="40.759010"  # Your latitude
export CALENDAR_WEATHER_LONGITUDE="-73.984474"  # Your longitude
export CALENDAR_TIMEZONE="America/New_York"  # Your timezone
```

These can be configured in several ways:

1. **Using the deployment script** - The automated installation script will prompt for these values
2. **Manually setting environment variables** - Add them to your `.bashrc` or `/etc/profile.d/`
3. **Using a .env file** - Create a `.env` file in the project root (not tracked by git)
4. **Setting at runtime** - Export before starting the application

The automated deployment script will handle this configuration for you, storing the values in `/etc/profile.d/family-calendar-env.sh`.

### Photo Management
Add new photos to the `src/static/photos/` directory. The application will automatically index them on the next restart.

## Usage

1. **Calendar View**:
   - Monthly calendar displayed on the left
   - Daily schedule shown on the right
   - Tasks/chores displayed in a dedicated section
   - Weather information always visible

2. **Inactivity Behavior**:
   - After a period of inactivity (default: 1 hour during day, 5 seconds at night), screen dims
   - PIR sensor instantly wakes display when motion is detected
   - When in long inactivity mode, slideshow activates
   - Any touch, mouse movement, keyboard press, or motion detection returns to calendar view
   - Reduced brightness during nighttime hours for energy saving

3. **PIR Sensor Operation**:
   - Continuously monitors for motion via GPIO pin 18
   - Automatic wake-up when people approach the display
   - Debug panel available (click "Debug" in bottom-right corner) for testing
   - Works in simulation mode for development without hardware

4. **Browser Access**:
   - The application can also be accessed from any device on your network
   - Navigate to `http://[raspberry-pi-ip]:5000` in any web browser

## Development

### Project Structure
```
src/
├── calendar_app/       # Core calendar functionality
│   ├── database.py     # Calendar database operations
│   ├── models.py       # Data models for calendar
│   └── utils.py        # Calendar utility functions
├── google_integration/ # Google API integration
│   ├── api.py          # Calendar API handling
│   └── tasks_api.py    # Tasks API for chores
├── pir_sensor/         # PIR motion sensor integration
│   ├── sensor.py       # GPIO sensor control and monitoring
│   └── routes.py       # Flask routes for sensor API
├── slideshow/          # Slideshow functionality
│   └── database.py     # Photo database management
├── static/             # Frontend assets
│   ├── css/            # CSS stylesheets
│   ├── js/             # JavaScript modules
│   │   └── components/ # Modular JS components including PIR sensor
│   └── photos/         # Photo storage
├── templates/          # HTML templates
├── weather_integration/# Weather functionality
└── main.py             # Application entry point
```

### Local Development

1. **Start the development server**:
   ```bash
   cd src
   python main.py
   ```

2. **Access the application**:
   Open a browser and navigate to `http://localhost:5000`

3. **Debug mode**:
   The Flask application runs in debug mode by default, allowing for hot reloading.

## Contributing

We welcome contributions from the community! Here's how you can help:

### Setting Up Development Environment

1. **Fork the repository**:
   - Click the Fork button at the top right of this page

2. **Clone your fork**:
   ```bash
   git clone https://github.com/Rasheed-bannister/family_calendar.git
   cd family-calendar
   ```

3. **Set up development environment**:
   ```bash
   uv venv
   source .venv/bin/activate
   uv pip install -e ".[dev]"
   ```

### Development Workflow

1. **Create a branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes**

3. **Test your changes locally**:
   ```bash
   python src/main.py
   ```

4. **Format code**:
   ```bash
   black src tests
   isort src tests
   ```

5. **Submit a Pull Request**:
   - Push to your fork
   - Create a Pull Request from the GitHub interface

### Coding Standards

- Follow PEP 8 guidelines for Python code
- Use ES6 modules for JavaScript
- Implement the component pattern for frontend features
- Include docstrings for all functions and classes
- Keep the UI simple and touch-friendly
- Ensure background tasks are properly threaded and use locks appropriately

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgements

- Weather data integration via Open-Meteo
- Google Calendar and Tasks API
- All photo credits to their respective photographers
- Special thanks to all contributors