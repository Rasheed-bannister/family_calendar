# CLAUDE.md

Guidance for Claude Code when working in this repository. Read
`docs/ARCHITECTURE.md` for the design; this file is about how to work here.

## Commands

### Backend (Python 3.11+, uv)
```bash
uv sync                       # create .venv and install (dev tools included)
uv run python -m src.main     # dev server on http://localhost:5000 (Flask dev server)
uv run waitress-serve --listen=127.0.0.1:5000 --threads=16 wsgi:app   # production path
uv run pytest -q              # tests
uv run pytest tests/display -v
uv run black src tests && uv run isort --profile black src tests && uv run ruff check --fix src tests
```

### Frontend (Node 22, Svelte 5, Vite)
```bash
cd frontend
npm ci
npm run dev        # http://localhost:5173, proxies API calls to Flask on :5000
npm run check      # svelte-check (must be 0 errors)
npm test           # vitest
npm run build      # writes src/static/app/ which Flask serves at /
```
Flask serves the *built* app. After changing anything under `frontend/src`,
run `npm run build` (or use `npm run dev`) or you will be looking at stale code.

### Deployment
`deploy_raspberry_pi.sh` (first install, idempotent), `upgrade.sh` (pull a
release, rebuild, restart), `scripts/pir_smoke_test.py` (hardware check).

## Ground rules

- **The server owns display state.** Do not add browser-side timers that
  hide/show the UI or reset idle. Activity reaches the server only through
  `POST /api/display/activity` (trusted input events) and the PIR callback.
- **Never dispatch synthetic DOM events** (`el.click()`, `dispatchEvent(new
  MouseEvent(...))`) in the frontend. Call store methods.
- **`create_app()` must stay side-effect free** beyond DB init and blueprint
  registration. Threads, GPIO, schedulers belong in `src/runtime.py`.
- **The PIR sensor is opened once per process.** No start/stop endpoints.
  A failure to open is an ERROR, surfaced on `/pir/status`, `/health/` and
  the on-screen badge; never fall back silently.
- **Publish change events only on real change.** Sync code compares before
  writing (`add_events`, chores) so a `*_changed` event never fires per sync.
- **One photo pipeline.** Anything that lands in `src/static/photos/` goes
  through `slideshow/ingest.py`; the frontend only ever loads
  `photos/processed/*.jpg`.
- **Z-index bands** (see `frontend/src/app.css`): slideshow 0, UI 10,
  modals/keyboard 100, toasts 200, dim overlay 1000. Nothing else.
- **No CDN assets** in the frontend; the Pi may be offline.
- Config: `config.json` (gitignored) with `config.default.json` as the
  template. New keys go in `Config.DEFAULTS` in `src/config.py` and, if
  the browser needs them, in `PUBLIC_CONFIG_KEYS` in `src/main.py`
  (never `app.secret_key`, `paths`, `logging`).

## Layout

```
src/            Flask app (see docs/ARCHITECTURE.md for the module table)
frontend/       Svelte app; builds into src/static/app/
tests/          pytest; tests/display/ covers the state machine with fake clocks
startup/        systemd unit, kiosk launcher, udev rule, health monitor
scripts/        pir_smoke_test.py, diagnose_pir.py
docs/           ARCHITECTURE.md
```

## Testing notes

- Tests never open GPIO, start the scheduler, or hit the network. Inject
  fakes with `set_display_service()` / `set_pir_sensor()` and patch
  `registry.tasks` / `registry.executor`.
- The state machine takes `clock` and `local_now` callables; test
  transitions by advancing a fake clock, never by sleeping.
- Slideshow tests point `slideshow.database.DATABASE_PATH` at a tmp file and
  generate small images with Pillow.
