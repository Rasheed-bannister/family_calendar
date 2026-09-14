#!/usr/bin/env python3
"""Five-line answer to "is the PIR sensor wired up and readable?".

Run on the Pi from the project's virtualenv, with the service STOPPED (the
service holds the pin while it runs):

    sudo systemctl stop family-calendar
    .venv/bin/python scripts/pir_smoke_test.py [--pin 18] [--seconds 30]
    sudo systemctl start family-calendar

Prints the pin factory in use and a line for every motion event. If it fails
to open the pin, the error message is the real reason (permissions, missing
lgpio, wrong pin), which is exactly what the app would have hit.
"""

import argparse
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pin", type=int, default=18, help="BCM GPIO pin (default 18)")
    parser.add_argument("--seconds", type=int, default=30, help="how long to listen")
    args = parser.parse_args()

    try:
        from gpiozero import MotionSensor
    except ImportError as e:
        print(f"gpiozero is not installed in this Python: {e}")
        print("Install with: uv sync  (needs the swig and liblgpio-dev packages)")
        return 2

    try:
        sensor = MotionSensor(args.pin, queue_len=1, sample_rate=10, threshold=0.5)
    except Exception as e:
        print(f"Could not open GPIO {args.pin}: {type(e).__name__}: {e}")
        print(
            "Check: user in 'gpio' group? /dev/gpiochip0 accessible? service stopped?"
        )
        return 1

    print(
        f"Listening on GPIO {args.pin} via {type(sensor.pin_factory).__name__} "
        f"for {args.seconds}s. Wave at the sensor."
    )
    count = 0

    def on_motion():
        nonlocal count
        count += 1
        print(f"{time.strftime('%H:%M:%S')}  motion #{count}")

    sensor.when_motion = on_motion
    try:
        time.sleep(args.seconds)
    except KeyboardInterrupt:
        pass
    finally:
        sensor.close()

    print(
        f"Done: {count} motion event(s). Raw value at exit: {sensor.value if not sensor.closed else 'n/a'}"
    )
    if count == 0:
        print(
            "No motion seen. HC-SR501 tips: 5V on VCC, OUT to the pin, allow ~60s warm-up, "
            "check the sensitivity/time pots and the retrigger jumper."
        )
    return 0 if count else 3


if __name__ == "__main__":
    sys.exit(main())
