#!/bin/bash

# Launch Family Calendar with PIR sensor support
echo "Starting Family Calendar application..."

cd ~/Desktop/calendar && source .venv/bin/activate

# Check GPIO permissions for PIR sensor
if ! groups | grep -q gpio; then
    echo "Warning: User not in gpio group. PIR sensor may not work."
    echo "Run: sudo usermod -a -G gpio $USER && reboot"
fi

# Start the application with PIR sensor support
python -m src.main &

echo "Family Calendar started with PIR sensor integration"