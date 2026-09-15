# Architecture

A wall-mounted family calendar for a Raspberry Pi touchscreen. Flask backend,
Svelte single-page frontend, SQLite caches, Google Calendar/Tasks sync, an
always-on photo slideshow behind a glass UI, and a PIR sensor that wakes the
screen.

## The one rule

**The server owns the display state.** Whether the screen is active, dimmed
or showing only the slideshow is decided by `src/display/state.py` on the Pi,
from three inputs it can actually see: PIR motion, real touches the page
reports, and the time of day. The browser renders that state and nothing
else. No timer in the browser can hide or show the UI, and no DOM event,
synthetic or otherwise, can reset the idle clock.

This is the fix for the class of bug where a calendar re-render called
`click()` on today's cell, the activity tracker counted it as a person, and
the display never went to sleep while Google sync was working.

## Backend (`src/`)

| Module | Role |
| --- | --- |
| `main.py` | `create_app()`: blueprints, JSON APIs, serves the built frontend at `/`. Never starts threads or hardware. |
| `runtime.py` | `start_runtime(app)`: the once-per-process things. Display service, PIR sensor, background sync scheduler, photo ingest. Called by `python -m src.main` and by `wsgi.py`. |
| `display/state.py` | `DisplayStateMachine`: pure logic, injectable clock. Modes `active → dimmed → slideshow` from idle seconds against day/night `Thresholds`. |
| `display/service.py` | 1 Hz ticker; on change sets the backlight and publishes `display_changed` over SSE. `activity(source)` is the only way to reset idle. |
| `display/backlight.py` | `sysfs` (official touchscreen, most panels), `ddcutil` (HDMI DDC/CI), or `none` (browser overlay fallback). |
| `display/routes.py` | `GET /api/display`, `POST /api/display/activity`, `POST /api/display/sleep`. |
| `pir_sensor/sensor.py` | gpiozero `MotionSensor`, opened once at startup, closed at exit. No HTTP start/stop. Fails loudly (log ERROR, `/pir/status.error`, `/health/` warning, on-screen badge). |
| `events.py` | SSE broker. One `/events` stream per display carries `display_changed`, `motion_detected`, `calendar_changed`, `chores_changed`, `photos_changed`, `weather_changed`. |
| `calendar_app/` | SQLite cache of Google Calendar events. `GET /api/calendar/<y>/<m>` returns the month grouped by day; `add_events` diffs before writing so `calendar_changed` is only published on real change. |
| `chores_app/` | Google Tasks mirror. `GET /api/chores`, `POST /chores/add`, `POST /chores/update_status/<id>`. |
| `weather_integration/` | Open-Meteo, cached on disk, refreshed in the background. `GET /api/weather` never touches the network. No pandas/numpy. |
| `slideshow/ingest.py` | One pipeline for every photo: EXIF transpose, RGB, resize to `slideshow.max_dimension`, progressive JPEG in `photos/processed/`. Records width/height so the frontend can choose cover vs. contain. |
| `slideshow/database.py` | Index of originals and variants; `next_photo()` is a shuffle bag (every photo once before repeats). |
| `photo_upload/` | Phone upload page with QR/token auth (unchanged pages, EXIF fix on save). |
| `health_monitor.py` | `/health/` includes `hardware.pir` and `hardware.display`. |
| `scheduler.py`, `sync_state.py` | Background job ticker and the task registry that deduplicates syncs. |

### Display state

```
                activity(source)            evaluate() each second
ACTIVE ─────────────────────────┐    ┌──── idle ≥ dim_after ──────► DIMMED
  ▲                             │    │                                │
  └── any activity ◄────────────┴────┴──── idle ≥ hide_ui_after ────► SLIDESHOW
```

`display.day` and `display.night` in `config.json` each hold
`dim_after_seconds`, `hide_ui_after_seconds` and `brightness`. Night is the
window `[night_start_hour, night_end_hour)`, wrapping midnight. Old
`inactivity` sections are migrated automatically on load.

Activity sources: `pir` (sensor callback), and `touch`/`pointer`/`keyboard`/
`wheel` from the page. The page only reports events with `isTrusted`.

### Brightness

When a hardware backlight is available the server sets it and tells the
page `overlay_brightness: 1.0`, so nothing is dimmed twice. Otherwise the
page dims with a single full-screen overlay at the very top of the stack
(`z-index 1000`), above modals and toasts.

## Frontend (`frontend/`)

Svelte 5 + TypeScript, built by Vite into `src/static/app/` and served by
Flask. No CDN dependencies; works offline.

```
src/
  App.svelte                 shell: slideshow, .ui layer (fades out in slideshow mode), overlay
  app.css                    tokens, glass look, the z-index bands
  lib/api.ts                 typed client for every endpoint
  lib/sse.ts                 one EventSource, backoff, fallback poll hook
  lib/activity.ts            trusted input → display.activity()
  lib/stores/*.svelte.ts     runes-based stores: display, config, calendar, chores, weather, toasts, keyboard
  components/
    Slideshow.svelte         two-layer crossfade, Ken Burns, contain+blur for mismatched aspect
    DimOverlay.svelte        CSS fallback dimming
    CalendarPanel / DayView / EventModal / DatePickerModal / QrModal
    Chores / AddChoreModal / VirtualKeyboard
    Weather / SettingsPanel / Toasts / MotionBadge / Modal
```

Stacking, bottom to top: slideshow (0) → UI (10) → modals and keyboard
(100) → toasts and motion badge (200) → dim overlay (1000).

Development: `cd frontend && npm run dev` (proxies to Flask on :5000),
`npm run check`, `npm test`, `npm run build`.

## Deployment

`deploy_raspberry_pi.sh` (Bookworm, Wayland): system packages including
Node 22 and chromium, `uv sync`, `npm run build`, groups `gpio video i2c`,
the backlight udev rule, `family-calendar.service` (waitress + `wsgi.py`),
kiosk browser autostart (`startup/launch-browser.sh`), blanking off.
`upgrade.sh` and the in-app updater rebuild the frontend on every upgrade.

The systemd unit deliberately has **no** `DeviceAllow=` lines: with any
present, systemd switches to a closed device policy, and the old
`/dev/gpiochip*` glob was never expanded, which is what denied the PIR
sensor its device on a Pi 5.

## Checking a deployment

```
curl -s localhost:5000/health/ | python3 -m json.tool      # status, hardware.pir, hardware.display
curl -s localhost:5000/pir/status                          # available / error
curl -s localhost:5000/pir/diagnostics | python3 -m json.tool
curl -s localhost:5000/api/display                         # mode, idle, backlight
curl -s -X POST localhost:5000/api/display/sleep           # force the slideshow
sudo systemctl stop family-calendar && .venv/bin/python scripts/pir_smoke_test.py
```
