"""Server-owned display state.

The display has three modes -- active, dimmed, slideshow -- and exactly one
owner: the state machine in :mod:`src.display.state`, driven by
:mod:`src.display.service`. The browser is a renderer of that state, never a
source of truth for it.

Why the server owns this
------------------------
Everything that decides the mode is a server-side fact: the PIR sensor is
wired to the Pi, the time of day is the Pi's clock, and the backlight is a
sysfs file on the Pi. The previous design kept the timers in the browser,
where any synthetic DOM event (a calendar re-render calling ``click()`` on
today's cell, for instance) was indistinguishable from a person touching the
screen and silently reset the clock. Here, activity is an explicit call --
from the PIR callback or from a throttled POST the page sends on real input
events -- and nothing else can move it.
"""
