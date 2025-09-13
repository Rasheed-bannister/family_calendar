#!/usr/bin/env python3

import os
import sys

# Add src to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from google_integration import api as google_api  # noqa: E402


def check_google_events():
    """Check what events Google Calendar API is returning"""
    print("🔍 Checking Google Calendar API directly...")

    # Get Google Calendar service
    service = google_api.get_calendar_service()
    if not service:
        print("❌ Failed to get Google Calendar service")
        return

    # Get current month events
    month = 6
    year = 2025

    print(f"📅 Fetching events for {month}/{year}...")
    events = google_api.get_events_current_month(service, month, year)

    print(f"📊 Found {len(events)} total events from Google Calendar API")

    # Look for the specific duplicate event
    katherine_events = [
        e for e in events if "katherine out of town" in e.get("summary", "").lower()
    ]

    if katherine_events:
        print(f"\n🔍 Found {len(katherine_events)} 'katherine out of town' events:")
        for i, event in enumerate(katherine_events, 1):
            print(f"   {i}. ID: {event.get('id', 'N/A')[:12]}...")
            print(f"      Summary: {event.get('summary', 'N/A')}")
            print(f"      Calendar: {event.get('organizer', {}).get('email', 'N/A')}")
            print(
                f"      Start: {event.get('start', {}).get('dateTime', event.get('start', {}).get('date', 'N/A'))}"
            )
            print(f"      Status: {event.get('status', 'N/A')}")
            print()
    else:
        print("\n🔍 No 'katherine out of town' events found in Google Calendar API")

    # Show all events for debugging
    print("\n📋 All events from Google Calendar API:")
    for i, event in enumerate(events, 1):
        summary = event.get("summary", "No Title")
        event_id = event.get("id", "N/A")[:12]
        calendar = event.get("organizer", {}).get("email", "N/A")
        start = event.get("start", {}).get(
            "dateTime", event.get("start", {}).get("date", "N/A")
        )
        status = event.get("status", "N/A")
        print(f"   {i:2d}. {summary} ({event_id}...) [{calendar}] {start} [{status}]")


if __name__ == "__main__":
    check_google_events()
