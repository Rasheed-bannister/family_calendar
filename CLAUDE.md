# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build and Development Commands

### Development Setup
```bash
# Install dependencies using UV package manager
uv venv
source .venv/bin/activate
uv pip install -e .

# Install development dependencies
uv pip install -e ".[dev]"
```

### Running the Application
```bash
# Start the Flask development server
uv run src/main.py

# Or if venv is activated
python src/main.py

# Application runs on http://localhost:5000
```

### Testing
```bash
# Run all tests
uv run pytest

# Run specific test module
uv run pytest tests/calendar_app/test_routes.py

# Run with verbose output
uv run pytest -v

# Run specific test function
uv run pytest tests/calendar_app/test_routes.py::test_function_name
```

### Code Quality

#### Automated Code Quality (Recommended)
```bash
# Smart commit that auto-handles formatting and fixes
./git-smart-commit.sh "your commit message"

# Or using the git alias
git smart-commit "your commit message"
```

The smart commit script automatically:
- Runs pre-commit hooks
- Auto-fixes formatting, import sorting, and linting issues
- Includes the fixes in the commit
- Only fails if there are unfixable issues

#### Manual Code Quality Tools
```bash
# Format code with Black
uv run black src tests

# Sort imports with isort
uv run isort src tests

# Lint with Ruff (auto-fix)
uv run ruff check --fix src tests

# Type checking with MyPy
uv run mypy src

# Security scanning with Bandit
uv run bandit -r src

# Complexity analysis with Radon
uv run radon cc src --show-closures

# Dead code detection with Vulture
uv run vulture src --min-confidence 80
```

#### Pre-commit Hooks
Pre-commit hooks are configured to run automatically on commit and include:
- Code formatting (Black, isort, Ruff)
- Security scanning (Bandit)
- Type checking (MyPy)
- Dead code detection (Vulture)
- Complexity analysis
- Import validation

```bash
# Install pre-commit hooks
uv run pre-commit install

# Run hooks manually on all files
uv run pre-commit run --all-files
```

## Architecture Overview

### Core Structure
The application is a Flask-based family calendar system with touchscreen support, designed primarily for Raspberry Pi deployment. It follows a modular architecture where each major feature is a separate Flask blueprint.

### Key Components

**Main Application (`src/main.py`)**
- Application factory pattern with `create_app()`
- Global locks for thread-safe Google API operations (`google_fetch_lock`)
- Background task tracking dictionary (`background_tasks`) for calendar syncing
- PIR sensor initialization for motion detection
- Health monitoring with automatic error recovery

**Module Organization**
- `calendar_app/`: Core calendar functionality with SQLite database
- `google_integration/`: Google Calendar & Tasks API integration with OAuth2
- `weather_integration/`: Open-Meteo weather API integration with caching
- `slideshow/`: Photo slideshow management with database tracking
- `pir_sensor/`: GPIO-based PIR motion sensor for automatic display wake
- `chores_app/`: Task/chore management synced with Google Tasks
- `photo_upload/`: Secure mobile photo upload system with token authentication
- `health_monitor.py`: System health monitoring and error recovery
- `config.py`: Centralized configuration management

**Frontend Architecture & UI System**
- Component-based JavaScript modules (ES6) in `static/js/components/`
- **Layered UI Design**: Background slideshow runs continuously with transparent glass-style UI overlays
- **Always-On Slideshow**: Photo slideshow (`slideshow.js`) runs permanently in background at z-index -1/-2
- **Transparent Overlays**: Calendar, weather, chores, and other UI elements use transparent/glass styling
- **Inactivity Modes**: UI overlays hide/show based on user activity, slideshow remains constant
- Central `app.js` coordinates inactivity detection and mode switching
- Virtual keyboard for touchscreen text input
- Server-Sent Events (SSE) for real-time PIR sensor updates at `/pir/stream`

**Activity Detection & Mode Management**
- **User Activity**: Screen touches, PIR motion detection, keyboard/mouse events
- **Day/Night Inactivity Timeouts**: Configurable timeouts with different behavior for day vs night
- **Short Inactivity**: UI dims with brightness reduction overlay (z-index -10, below slideshow)
- **Long Inactivity**: All UI elements hide (`display: none`), showing only the background slideshow
- **Wake Behavior**: Any activity instantly restores UI overlays over the continuing slideshow

**Data Flow**
1. Background threads periodically sync Google Calendar/Tasks data
2. SQLite databases cache events locally for fast retrieval
3. Frontend polls `/check-updates` endpoint for changes
4. PIR sensor events trigger immediate UI updates via SSE
5. **Slideshow**: Continuously cycles photos with 30-second intervals and 10-second preloading

### Threading Model
- Main Flask thread handles web requests
- Separate background threads for Google API syncing per month/year
- Thread-safe operations using `google_fetch_lock`
- PIR sensor runs in its own thread with GPIO monitoring
- Background tasks tracked in `background_tasks` dictionary to prevent duplicates

### Database Schema
- `calendar.db`: Calendar events with month/year indexing
- `slideshow.db`: Photo metadata and tracking
- `chores.db`: Task/chore storage synced with Google Tasks

### Configuration System
- Primary configuration in `config.json` (auto-generated if missing)
- Environment variable fallback for backwards compatibility
- Configuration accessible via `src.config.get_config()`
- Production vs development mode handling in config

## Important Considerations

### Google API Authentication
- Credentials must be placed in `src/google_integration/credentials.json`
- OAuth2 tokens stored in `*_token.json` files (calendar_token.json, tasks_token.json)
- First run requires manual OAuth authorization via browser redirect
- Thread-safe API operations using `google_fetch_lock`

### PIR Sensor Integration
- Uses GPIO pin 18 by default (configurable in config.json)
- Falls back to simulation mode if GPIO unavailable (for development)
- Real-time communication via Server-Sent Events at `/pir/stream`
- Debounce protection with 2-second default delay

### Deployment Specifics
- Designed for Raspberry Pi 5 with touchscreen
- Full deployment script: `deploy_raspberry_pi.sh`
- Startup scripts in `startup/` directory:
  - `launch.sh`: Main launcher script
  - `launch-calendar.sh`: Calendar app startup
  - `family-calendar.service`: Systemd service file
  - `health-monitor.sh`: Health monitoring script
- Configuration via `config.json` or environment variables:
  - CALENDAR_WEATHER_LATITUDE
  - CALENDAR_WEATHER_LONGITUDE
  - CALENDAR_TIMEZONE

### Frontend State Management & Critical Z-Index Architecture
- **CRITICAL Z-Index Layering** (must be preserved for proper dimming and slideshow):
  - **Slideshow backgrounds**: z-index -1 and -2 (always visible, constantly running)
  - **UI elements**: z-index 0+ (transparent overlays above slideshow)
  - **Brightness overlay**: z-index 100 (above everything to dim entire screen including slideshow)
- **Activity Detection**: Screen touches, PIR motion, keyboard/mouse events
- **Inactivity Modes**:
  - **Active**: All UI overlays visible over slideshow, full brightness
  - **Short Inactive**: Brightness overlay dims everything (UI + slideshow)
  - **Long Inactive**: UI hidden completely, brightness overlay dims slideshow-only view
- **PIR Flash Suppression**: `body.slideshow-active` class permanently disables motion animations
- **State Transitions**: Managed by `app.js` inactivity detection system

### Photo Upload System
- **Security**: Token-based authentication with HMAC-SHA256 signatures and 60-minute expiration
- **Mobile Access**: QR code generation at `/photo-upload/qr` for secure mobile uploads
- **File Processing**: Automatic HEIC to JPEG conversion for iPhone compatibility
- **Rate Limiting**: 10 uploads per minute, 100 per hour per device/token
- **Image Optimization**: Automatic resizing to max 1920px and thumbnail generation
- **Cross-Origin**: CORS headers configured for mobile browser compatibility
- **File Validation**: Size limits (16MB), format validation (JPG, PNG, HEIC, WebP, GIF)

### Photo Upload Security Features
- **Token Generation**: Cryptographically secure tokens with HMAC-SHA256 signatures
- **IP Binding**: Tokens optionally bound to client IP addresses (with NAT tolerance)
- **Usage Limits**: Maximum 100 uses per token with automatic cleanup
- **Rate Limiting**: Per-device request throttling to prevent abuse
- **Input Validation**: File type, size, and content validation before processing
- **Secure Storage**: Photos stored in `src/static/photos/` with unique identifiers

### Health Monitoring
- Automatic error tracking and recovery in `health_monitor.py`
- Configurable restart thresholds for critical errors
- Background task monitoring and cleanup
- Service status endpoints at `/health/*`

### Testing Structure
- Test files organized by module in `tests/` directory
- Each module has corresponding test files (e.g., `tests/calendar_app/`)
- Use pytest fixtures for database and app setup
- Mock Google API calls to avoid external dependencies
