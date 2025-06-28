#!/bin/bash

# PIR Sensor Test Script for Family Calendar
# Tests PIR sensor connectivity and functionality

# ANSI color codes
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}===${NC} ${GREEN}PIR Sensor Test${NC} ${BLUE}===${NC}\n"

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
APP_DIR="$(dirname "$SCRIPT_DIR")"

echo -e "${YELLOW}Testing PIR sensor for Family Calendar application...${NC}\n"

# Check if we're in the right directory
if [ ! -f "$APP_DIR/src/main.py" ]; then
    echo -e "${RED}ERROR:${NC} Cannot find Family Calendar application"
    echo "Please run this script from the startup directory"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "$APP_DIR/.venv" ]; then
    echo -e "${RED}ERROR:${NC} Python virtual environment not found"
    echo "Please run the deployment script first"
    exit 1
fi

cd "$APP_DIR"
source .venv/bin/activate

echo -e "${YELLOW}1. Testing GPIO availability...${NC}"
python -c "
import sys
try:
    import RPi.GPIO as GPIO
    print('✓ RPi.GPIO module available')
    GPIO.setmode(GPIO.BCM)
    GPIO.cleanup()
    print('✓ GPIO initialization successful')
except ImportError:
    print('✗ RPi.GPIO module not available (install with: sudo apt install python3-rpi.gpio)')
    sys.exit(1)
except Exception as e:
    print(f'✗ GPIO error: {e}')
    sys.exit(1)
"

if [ $? -ne 0 ]; then
    echo -e "${RED}GPIO test failed${NC}"
    exit 1
fi

echo -e "\n${YELLOW}2. Testing PIR sensor integration...${NC}"
python -c "
from src.pir_sensor.sensor import PIRSensor
import time

try:
    sensor = PIRSensor(pin=18)
    print(f'✓ PIR sensor object created (GPIO available: {sensor.gpio_available})')
    
    if sensor.setup():
        print('✓ PIR sensor setup successful')
    else:
        print('✗ PIR sensor setup failed')
        exit(1)
        
    print('✓ PIR sensor ready for motion detection')
except Exception as e:
    print(f'✗ PIR sensor error: {e}')
    exit(1)
"

if [ $? -ne 0 ]; then
    echo -e "${RED}PIR sensor test failed${NC}"
    exit 1
fi

echo -e "\n${YELLOW}3. Testing application integration...${NC}"
python -c "
from src.pir_sensor.sensor import initialize_pir_sensor

try:
    def test_callback():
        print('Motion detected callback triggered!')
    
    sensor = initialize_pir_sensor(pin=18, callback=test_callback)
    print('✓ PIR sensor initialized with callback')
    print('✓ Application integration successful')
except Exception as e:
    print(f'✗ Integration error: {e}')
    exit(1)
"

if [ $? -ne 0 ]; then
    echo -e "${RED}Integration test failed${NC}"
    exit 1
fi

echo -e "\n${GREEN}✓ All PIR sensor tests passed!${NC}\n"

echo -e "${BLUE}Hardware Connection Guide:${NC}"
echo -e "Connect your PIR sensor as follows:"
echo -e "• PIR VCC → Raspberry Pi Pin 2 or 4 (5V)"
echo -e "• PIR GND → Raspberry Pi Pin 6 (Ground)"
echo -e "• PIR OUT → Raspberry Pi Pin 12 (GPIO 18)"
echo -e ""
echo -e "${BLUE}Testing Motion Detection:${NC}"
echo -e "1. Start the application: bash $APP_DIR/startup/launch.sh"
echo -e "2. Open browser to http://localhost:5000"
echo -e "3. Click 'Debug' in bottom-right corner"
echo -e "4. Use 'Test Motion' button or move in front of PIR sensor"
echo -e "5. Watch for motion detection messages in debug panel"

echo -e "\n${GREEN}PIR sensor is ready for use!${NC}"
