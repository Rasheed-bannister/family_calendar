#!/bin/bash

echo "Starting Family Calendar application..."

# Get the directory where this script is located (startup directory)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# Navigate to parent directory (project root)
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR" || { echo "Failed to navigate to project directory"; exit 1; }

# Check if virtual environment exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "Warning: Virtual environment not found at $PROJECT_DIR/.venv"
    echo "Attempting to run with system Python..."
fi

# Check GPIO permissions for PIR sensor
if ! groups | grep -q gpio; then
    echo "Warning: User not in gpio group. PIR sensor may not work."
    echo "Run: sudo usermod -a -G gpio $USER && reboot"
fi

python -m src.main &

echo "Family Calendar started with PIR sensor integration"
echo "Project directory: $PROJECT_DIR"