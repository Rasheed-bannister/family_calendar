import datetime
import logging
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_file

# Import configuration
from src.config import get_config

# Background sync state. Lives in its own module so blueprints can import it
# without importing src.main, which would be an import cycle.
from src.scheduler import scheduler
from src.sync_state import registry

logger = logging.getLogger(__name__)

# Backwards-compatible aliases, bound to the *same* objects the registry uses.
# Read-only; use ``src.sync_state.registry`` in application code and tests.
background_tasks: dict[str, dict] = registry.tasks
google_fetch_lock = registry.lock
sync_executor = registry.executor

# Where `npm run build` (in frontend/) writes the compiled single-page app.
# Served by Flask's static route at /static/app/...; the index is served at /.
FRONTEND_DIST_REL = Path("app")


# Allowlist of configuration values exposed to the browser via /api/config.
#
# Nothing else may be added here without checking it is not sensitive: the
# "app" section holds secret_key (session cookie + photo-upload token signing
# key), and "paths"/"logging" leak filesystem layout.
PUBLIC_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    "app": ("family_name", "debug", "environment"),
    "display": ("night_start_hour", "night_end_hour"),
    "slideshow": ("interval_seconds", "transition_seconds", "ken_burns"),
    "google": ("sync_interval_minutes",),
    "weather": ("cache_duration",),
    "ui": ("show_pir_feedback", "touch_optimized", "animation_duration_ms"),
}


def _build_public_config(config) -> dict:
    """Build the browser-safe view of the configuration."""
    public: dict = {}
    for section, keys in PUBLIC_CONFIG_KEYS.items():
        section_values = config.get(section) or {}
        public[section] = {
            key: section_values[key] for key in keys if key in section_values
        }
    # Nested day/night thresholds are safe and useful for the UI's countdown.
    public["display"]["day"] = config.get("display.day") or {}
    public["display"]["night"] = config.get("display.night") or {}
    from src.config import get_timezone_name

    public["app"]["timezone"] = get_timezone_name()
    return public


def clear_stale_background_tasks():
    """Clear any stale background tasks from previous runs."""
    registry.clear()


def _sync_interval_seconds() -> float:
    return get_config().get("google.sync_interval_minutes", 5) * 60


def _weather_interval_seconds() -> float:
    return get_config().get("weather.cache_duration", 600)


def _sync_current_month_calendar() -> None:
    """Keep the month the display is showing today up to date.

    The scheduler has no idea which month a browser is looking at, so it
    covers the common case -- today's month -- and the month API queues an
    on-demand sync when someone navigates elsewhere. Both go through the
    registry, so whichever gets there first wins and the other is
    deduplicated rather than doing the work twice.
    """
    from src.config import get_local_timezone
    from src.google_integration.routes import calendar_task_id, start_calendar_sync

    now = datetime.datetime.now(tz=get_local_timezone())
    if registry.is_stale(
        calendar_task_id(now.month, now.year), _sync_interval_seconds()
    ):
        start_calendar_sync(now.month, now.year)


def _sync_chores() -> None:
    from src.google_integration.routes import TASKS_TASK_ID, start_tasks_sync

    if registry.is_stale(TASKS_TASK_ID, _sync_interval_seconds()):
        start_tasks_sync()


def _sync_weather() -> None:
    from src.weather_integration.routes import start_weather_background_refresh

    start_weather_background_refresh()


def register_sync_jobs(sched) -> None:
    """Register the recurring sync jobs on a scheduler.

    Each job only *queues* work on the registry's pool; none of them block
    the scheduler thread on a network call.
    """
    sched.add_job("calendar", _sync_current_month_calendar, _sync_interval_seconds)
    sched.add_job("chores", _sync_chores, _sync_interval_seconds)
    sched.add_job("weather", _sync_weather, _weather_interval_seconds)


def start_background_sync():
    """Start the periodic sync scheduler. Returns the scheduler.

    Called by :func:`src.runtime.start_runtime` rather than by create_app(),
    because a scheduler is a process-level concern: create_app() is invoked
    many times across the test suite and by tooling, and none of those should
    spawn a thread that reaches out to the Google APIs.
    """
    if not get_config().get("scheduler.enabled", True):
        logger.info("Sync scheduler disabled by configuration")
        return scheduler

    register_sync_jobs(scheduler)
    scheduler.start()
    return scheduler


_NOT_BUILT_PAGE = """<!doctype html>
<meta charset="utf-8"><title>Family Calendar</title>
<body style="font-family:sans-serif;background:#111;color:#eee;padding:2rem">
<h1>Frontend not built</h1>
<p>The compiled app was not found at <code>{path}</code>.</p>
<p>Build it with:</p>
<pre>cd frontend &amp;&amp; npm ci &amp;&amp; npm run build</pre>
<p>or run <code>./deploy_raspberry_pi.sh</code> / <code>./upgrade.sh</code>, which do this for you.</p>
</body>"""


def create_app():
    """Application factory to create and configure the Flask app."""
    config = get_config()

    # Clear any stale background tasks from previous runs
    clear_stale_background_tasks()

    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.get("app.secret_key")

    # Reject oversized request bodies at the WSGI boundary instead of letting
    # Werkzeug buffer an unbounded upload onto the Pi's SD card first.
    from src.photo_upload.routes import MAX_UPLOAD_CONTENT_LENGTH

    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_CONTENT_LENGTH

    # Initialize health monitoring
    from src.health_monitor import health_monitor

    @app.errorhandler(500)
    def handle_500_error(error):
        health_monitor.record_error(
            "Internal Server Error", str(error), is_critical=True
        )
        return "Internal Server Error", 500

    @app.errorhandler(413)
    def handle_request_too_large(error):
        """Answer oversized request bodies with JSON rather than an HTML page."""
        limit = app.config.get("MAX_CONTENT_LENGTH")
        limit_mb = round(limit / (1024 * 1024)) if limit else None
        message = "Upload too large"
        if limit_mb:
            message = f"{message}. Maximum request size is {limit_mb}MB"
        return jsonify({"error": message}), 413

    @app.errorhandler(Exception)
    def handle_exception(error):
        # Don't handle HTTP exceptions (like 404, 403) as critical
        if hasattr(error, "code"):
            return error

        should_restart = health_monitor.record_error(
            "Unhandled Exception", str(error), is_critical=True
        )
        if should_restart:
            logging.critical(
                "Application restart threshold reached due to critical errors"
            )
            health_monitor.trigger_restart()

        return "Internal Server Error", 500

    # Databases
    from src.calendar_app.utils import initialize_db as initialize_calendar_db

    initialize_calendar_db()

    from src.chores_app.utils import initialize_db as initialize_chores_db

    initialize_chores_db()

    from src.slideshow import database as slideshow_db

    slideshow_db.init_db()

    # Blueprints
    from src.calendar_app.routes import calendar_bp
    from src.chores_app.routes import chores_bp
    from src.display.routes import display_bp
    from src.google_integration import google_bp
    from src.health_routes import health_bp
    from src.photo_upload.auth import init_token_manager
    from src.photo_upload.routes import upload_bp
    from src.pir_sensor.routes import pir_bp
    from src.slideshow.routes import slideshow_bp
    from src.weather_integration.routes import weather_bp

    app.register_blueprint(calendar_bp)
    app.register_blueprint(slideshow_bp)
    app.register_blueprint(weather_bp)
    app.register_blueprint(chores_bp)
    app.register_blueprint(google_bp)
    app.register_blueprint(pir_bp)
    app.register_blueprint(display_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(upload_bp)

    init_token_manager(app)

    frontend_index = Path(app.static_folder) / FRONTEND_DIST_REL / "index.html"

    def _serve_frontend():
        if frontend_index.is_file():
            response = send_file(frontend_index, mimetype="text/html")
            # The index references hashed asset names; never let a stale
            # index outlive a rebuild.
            response.headers["Cache-Control"] = "no-store"
            return response
        return Response(
            _NOT_BUILT_PAGE.format(path=frontend_index), mimetype="text/html"
        )

    @app.route("/")
    def index():
        """The single-page display app."""
        return _serve_frontend()

    @app.route("/calendar/")
    @app.route("/calendar/<int:year>/<int:month>")
    def legacy_calendar_view(year: int = None, month: int = None):
        """Old bookmarkable URLs still open the app (month via the query string)."""
        from flask import redirect, url_for

        if year and month:
            return redirect(url_for("index", year=year, month=month))
        return redirect(url_for("index"))

    @app.route("/events")
    def events_stream():
        """Single SSE stream carrying every notification for the display."""
        from src import events as events_mod
        from src.events import broker

        return Response(
            broker.stream(),
            mimetype="text/event-stream",
            headers=events_mod.sse_headers(),
        )

    @app.route("/api/config")
    def get_config_api():
        """Browser-safe subset of the configuration (see PUBLIC_CONFIG_KEYS)."""
        return jsonify(_build_public_config(get_config()))

    @app.route("/api/version")
    def version_api():
        from src.version import check_for_update, get_current_version

        check = request.args.get("check_update", "").lower() == "true"
        if check:
            return jsonify(check_for_update())
        return jsonify({"current_version": get_current_version()})

    @app.route("/api/upgrade", methods=["POST"])
    def upgrade_api():
        """Trigger an application upgrade to the specified tag."""
        import re

        from src.version import start_upgrade

        # Restrict to localhost only — upgrades should not be triggered remotely
        if request.remote_addr not in ("127.0.0.1", "::1"):
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Upgrades allowed from localhost only",
                    }
                ),
                403,
            )

        data = request.get_json(silent=True) or {}
        tag = data.get("tag")
        if not tag:
            return jsonify({"success": False, "message": "Missing 'tag' field"}), 400

        if not re.match(r"^v\d+\.\d+\.\d+$", tag):
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Invalid tag format (expected vX.Y.Z)",
                    }
                ),
                400,
            )

        return jsonify(start_upgrade(tag))

    @app.route("/api/upgrade/status")
    def upgrade_status_api():
        """Upgrade progress. Localhost only, like the trigger: the messages
        can include git and build output."""
        from src.version import get_upgrade_status

        if request.remote_addr not in ("127.0.0.1", "::1"):
            return (
                jsonify(
                    {
                        "state": "unavailable",
                        "message": "Upgrade status is available from the display only",
                    }
                ),
                403,
            )
        return jsonify(get_upgrade_status())

    return app


if __name__ == "__main__":
    import sys

    setup_only = "--setup-only" in sys.argv

    app = create_app()

    if setup_only:
        logger.info("Setup completed. Exiting without starting server.")
        sys.exit(0)

    from src.runtime import start_runtime

    start_runtime(app)

    config = get_config()
    debug_mode = config.get("app.debug", False)
    host = config.get(
        "app.host", "0.0.0.0"
    )  # nosec B104 # Intentional for family calendar local network access
    port = config.get("app.port", 5000)
    use_reloader = config.get("app.use_reloader", False)

    if config.is_production() and debug_mode:
        logging.warning("Debug mode is enabled in production! Consider disabling it.")
        debug_mode = False

    # Ignore .db files to prevent reload loop caused by background updates
    app.run(
        host=host,
        port=port,
        debug=debug_mode,
        use_reloader=use_reloader,
        threaded=True,
        exclude_patterns=["**/*.db"],
    )
