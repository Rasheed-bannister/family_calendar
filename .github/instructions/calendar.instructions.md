---
applyTo: '**'
---
Coding standards, domain knowledge, and preferences that AI should follow.
# Production Hardware
- Raspberry Pi 5
- PIR sensor
- Touchscreen monitor

# Instructions for AI Agent
- actively check for and remove duplicate or unused code
- ensure code is efficient and follows best practices
- limit comments and logging statements to those that are absolutely necessary
- your mission is to find and fix errors in the code that pevent the app from performing as listed below:

# App Functionality
- single page app that displays a calendar, tasks, and weather with rotating images as the background
- the app should be responsive and work on a Raspberry Pi 5 with a touchscreen monitor. no cursor should be visible, as the touchscreen is the only input device
- the app should use a PIR sensor to detect motion and wake up the display when someone is nearby
- the app should quickly identify if changes were made to the google calendars and task list and update the display accordingly
- the app should have a screen saver that activates after a period of inactivity
- the app should be able to run in a kiosk mode, where it is the only app running on the Raspberry Pi 5
- the app should snap back to the current date and time after a period of inactivity
- the app must seamlessly transition to the following day after midnight