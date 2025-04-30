# Description
- Family calendar app and photo slideshow
- Runs on a Raspberry Pi, connected to a touchscreen monitor
- Designed for wall-mounting in common family areas

## Calendar App Features
- On the left 3/4 of the screen, displays a monthly calendar
- On the right 1/4 of the screen, displays an hourly breakdown of the current day's activities
- Calendar will integrate with Google Calendar and Apple Calendar via their APIs
- Users can tap on a button to add events directly from the interface
- Color-coding for different family members' events
- Notification alerts for upcoming events (configurable)
- Weather widget showing current conditions and forecast
- Support for recurring events and reminders

## Photo Slideshow Features
- After 5 minutes of no interaction, the photo slideshow will begin
- App will cycle through images in local storage, displaying each for 2 minutes
- Fade transition between images
- Tap on the screen will pull up the calendar view again
- Support for custom albums and categories
- Option to pull photos from cloud storage (Google Photos, iCloud)
- Automatic cropping/scaling for optimal display on the monitor

## Technical Requirements
- Python 3.13+ with Flask
- Data persistence using SQLite for local storage
- OAuth integration for calendar services
- Responsive design for different monitor sizes
- Boot on Raspberry Pi startup
- Low power mode during non-peak hours
- Touch interface optimization
- Backup/restore functionality for settings and local data