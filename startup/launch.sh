#!/bin/bash

# Family Calendar Launch Script
# Starts the complete Family Calendar application with PIR sensor support

echo "Starting Family Calendar & Photo Slideshow..."

cd ~/Desktop/calendar/startup

# Start the calendar application
./launch-calendar.sh

# Configure screensaver
./launch-screensaver.sh

# Give services time to start
sleep 5

# Launch browser in kiosk mode
./launch-browser.sh

echo "Family Calendar launched with PIR motion detection enabled"
echo "PIR sensor should be connected to GPIO 18 (Pin 12)"