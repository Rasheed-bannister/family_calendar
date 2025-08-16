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
```

### Code Quality
```bash
# Format code with Black
black src tests

# Sort imports with isort
isort src tests
```

## Architecture Overview

### Core Structure
The application is a Flask-based family calendar system with touchscreen support, designed primarily for Raspberry Pi deployment. It follows a modular architecture where each major feature is a separate Flask blueprint.

### Key Components

**Main Application (`src/main.py`)**
- Application factory pattern with `create_app()`
- Global locks for thread-safe Google API operations
- Background task tracking for calendar syncing
- PIR sensor initialization for motion detection

**Module Organization**
- `calendar_app/`: Core calendar functionality with SQLite database
- `google_integration/`: Google Calendar & Tasks API integration with OAuth2
- `weather_integration/`: Open-Meteo weather API integration
- `slideshow/`: Photo slideshow management with database tracking
- `pir_sensor/`: GPIO-based PIR motion sensor for automatic display wake
- `chores_app/`: Task/chore management synced with Google Tasks
- `photo_upload/`: Secure mobile photo upload system with token authentication

**Frontend Architecture**
- Component-based JavaScript modules (ES6) in `static/js/components/`
- Each component manages its own state and DOM updates
- Central app.js coordinates inactivity detection and mode switching
- Virtual keyboard for touchscreen text input
- Server-Sent Events (SSE) for real-time PIR sensor updates

**Data Flow**
1. Background threads periodically sync Google Calendar/Tasks data
2. SQLite databases cache events locally for fast retrieval
3. Frontend polls `/check-updates` endpoint for changes
4. PIR sensor events trigger immediate UI updates via SSE

### Threading Model
- Main Flask thread handles web requests
- Separate background threads for Google API syncing per month/year
- Thread-safe operations using `google_fetch_lock`
- PIR sensor runs in its own thread with GPIO monitoring

### Database Schema
- `calendar.db`: Calendar events with month/year indexing
- `slideshow.db`: Photo metadata and tracking
- `chores.db`: Task/chore storage synced with Google Tasks

## Important Considerations

### Google API Authentication
- Credentials must be placed in `src/google_integration/credentials.json`
- OAuth2 tokens are stored in `*_token.json` files
- First run requires manual OAuth authorization

### PIR Sensor Integration
- Uses GPIO pin 18 by default (configurable in main.py)
- Falls back to simulation mode if GPIO unavailable (for development)
- Real-time communication via Server-Sent Events at `/pir/stream`

### Deployment Specifics
- Designed for Raspberry Pi 5 with touchscreen
- Startup scripts in `startup/` handle kiosk mode and screensaver
- `deploy_raspberry_pi.sh` automates full installation
- Environment variables configure weather location (CALENDAR_WEATHER_LATITUDE, CALENDAR_WEATHER_LONGITUDE, CALENDAR_TIMEZONE)

### Frontend State Management
- Inactivity detection with configurable timeouts (day vs night)
- Three modes: active, inactive (dimmed), slideshow
- PIR motion instantly disrupts inactivity timers
- Touch/mouse/keyboard events also reset timers

### Photo Upload System
- **Security**: Token-based authentication with HMAC signatures and 60-minute expiration
- **Mobile Access**: QR code generation for secure mobile photo uploads
- **File Processing**: Automatic HEIC to JPEG conversion for iPhone compatibility
- **Rate Limiting**: 10 uploads per minute, 100 per hour per device/token
- **Image Optimization**: Automatic resizing and thumbnail generation
- **Cross-Origin**: CORS headers for mobile browser compatibility
- **File Validation**: Size limits (16MB), format validation, and secure filename handling

### Photo Upload Security Features
- **Token Generation**: Cryptographically secure tokens with HMAC-SHA256 signatures
- **IP Binding**: Tokens optionally bound to client IP addresses (with NAT tolerance)
- **Usage Limits**: Maximum 100 uses per token with automatic cleanup
- **Rate Limiting**: Per-device request throttling to prevent abuse
- **Input Validation**: File type, size, and content validation before processing
- **Secure Storage**: Photos stored with unique identifiers to prevent conflicts