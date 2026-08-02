import datetime
import logging

from flask import Flask, redirect, request, url_for

# Import configuration
from src.config import get_config

# Background sync state. Lives in its own module so blueprints can import it
# without importing src.main, which would be an import cycle.
from src.sync_state import registry

# Import utility functions
from src.weather_integration.utils import get_weather_icon

logger = logging.getLogger(__name__)

# Backwards-compatible aliases, bound to the *same* objects the registry uses.
#
# Read-only. Never patch these, and never write through them:
#   * writing to the task dict directly is what caused the sync wedges the
#     registry now prevents by construction;
#   * these names are bound once at import, so patching them (or patching
#     ``registry.tasks``) makes the two views diverge silently -- the alias
#     keeps pointing at the original object while production code reads the
#     replacement.
# Use ``src.sync_state.registry`` and its methods instead, in both application
# code and tests.
background_tasks: dict[str, dict] = registry.tasks
google_fetch_lock = registry.lock
sync_executor = registry.executor


# Allowlist of configuration values exposed to the browser via /api/config.
#
# The frontend is the only consumer of this endpoint, so this map mirrors
# exactly what the JS reads (see the loadConfig()/loadConfiguration() helpers in
# static/js/app.js, components/calendar.js, components/dailyView.js,
# components/loadingIndicator.js, components/pirSensor.js and
# components/virtualKeyboard.js).
#
# Nothing else may be added here without checking it is not sensitive: the
# "app" section holds secret_key (session cookie + photo-upload token signing
# key), and "paths"/"logging" leak filesystem layout. The nested section shape
# is load-bearing — the frontend indexes config.<section>.<key>, so flattening
# this would silently break every read.
PUBLIC_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    "inactivity": (
        "day_timeout_minutes",
        "night_timeout_seconds",
        "day_brightness_reduction",
        "night_brightness_reduction",
        "night_start_hour",
        "night_end_hour",
        "slideshow_delay_seconds",
    ),
    "google": ("sync_interval_minutes",),
    "ui": (
        "show_loading_indicators",
        "show_pir_feedback",
        "enhanced_virtual_keyboard",
        "touch_optimized",
        "animation_duration_ms",
    ),
}


def _build_public_config(config) -> dict[str, dict]:
    """Build the browser-safe view of the configuration.

    Args:
        config: The application Config instance.

    Returns:
        dict: Nested config sections containing only allowlisted keys.
    """
    public: dict[str, dict] = {}
    for section, keys in PUBLIC_CONFIG_KEYS.items():
        section_values = config.get(section) or {}
        public[section] = {
            key: section_values[key] for key in keys if key in section_values
        }
    return public


def clear_stale_background_tasks():
    """Clear any stale background tasks from previous runs."""
    registry.clear()


def create_app():
    """Application factory to create and configure the Flask app."""
    config = get_config()

    # Clear any stale background tasks from previous runs
    clear_stale_background_tasks()

    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.get("app.secret_key")

    # Reject oversized request bodies at the WSGI boundary instead of letting
    # Werkzeug buffer an unbounded upload onto the Pi's SD card first. The cap
    # is derived from the photo-upload contract (16MB per photo x 10 photos per
    # request, plus 1MB of multipart framing) because uploads are by far the
    # largest legitimate bodies this app accepts; see
    # src/photo_upload/routes.py for the constituent constants.
    from src.photo_upload.routes import MAX_UPLOAD_CONTENT_LENGTH

    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_CONTENT_LENGTH

    app.jinja_env.globals.update(get_weather_icon=get_weather_icon)

    # Initialize health monitoring
    from src.health_monitor import health_monitor

    # Set up global error handler for critical errors
    @app.errorhandler(500)
    def handle_500_error(error):
        health_monitor.record_error(
            "Internal Server Error", str(error), is_critical=True
        )
        return "Internal Server Error", 500

    @app.errorhandler(413)
    def handle_request_too_large(error):
        """Answer oversized request bodies with JSON rather than an HTML page.

        Werkzeug raises RequestEntityTooLarge once MAX_CONTENT_LENGTH is
        exceeded. Without this handler the request falls through to the
        catch-all Exception handler below, which returns the exception object
        unchanged; Flask then treats that HTTPException as a WSGI callable and
        renders its default HTML page. The photo upload UI parses every
        response as JSON, so it would surface a parse error instead of the
        real reason. A code-specific handler takes precedence over the
        class-based one, so this runs first.
        """
        from flask import jsonify

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

        # Log unhandled exceptions as critical errors
        should_restart = health_monitor.record_error(
            "Unhandled Exception", str(error), is_critical=True
        )

        if should_restart:
            logging.critical(
                "Application restart threshold reached due to critical errors"
            )
            health_monitor.trigger_restart()

        return "Internal Server Error", 500

    # Initialize database for calendar
    from src.calendar_app.utils import initialize_db as initialize_calendar_db

    initialize_calendar_db()

    # Initialize database for chores
    from src.chores_app.utils import initialize_db as initialize_chores_db

    initialize_chores_db()

    # Initialize and sync the slideshow database
    from src.slideshow import database as slideshow_db

    slideshow_db.init_db()
    slideshow_db.sync_photos(app.static_folder)

    # Register blueprints
    from src.calendar_app.routes import calendar_bp
    from src.chores_app.routes import chores_bp
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
    app.register_blueprint(health_bp)
    app.register_blueprint(upload_bp)

    # Initialize upload token manager
    init_token_manager(app)

    @app.route("/")
    def index_redirect():
        """Redirects the base URL to the current month's calendar view."""
        # Local time, not UTC — otherwise late on the last evening of a month
        # the landing page redirects to the *next* month.
        from src.config import get_local_timezone

        now = datetime.datetime.now(tz=get_local_timezone())
        return redirect(url_for("calendar.view", year=now.year, month=now.month))

    @app.route("/api/config")
    def get_config_api():
        """API endpoint exposing the browser-safe subset of configuration.

        Only the keys the frontend actually reads are returned. The full config
        object must never be serialized here: it contains ``app.secret_key``
        (used to sign session cookies and HMAC photo-upload tokens) as well as
        filesystem paths and logging settings.
        """
        from flask import jsonify

        config = get_config()
        return jsonify(_build_public_config(config))

    @app.route("/api/version")
    def version_api():
        """API endpoint to get current version and check for updates."""
        from flask import jsonify

        from src.version import check_for_update, get_current_version

        check = request.args.get("check_update", "").lower() == "true"
        if check:
            return jsonify(check_for_update())
        return jsonify({"current_version": get_current_version()})

    @app.route("/api/upgrade", methods=["POST"])
    def upgrade_api():
        """Trigger an application upgrade to the specified tag."""
        import re

        from flask import jsonify

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

        # Validate tag format (must look like a semver release tag)
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
        """Check the status of a running upgrade."""
        from flask import jsonify

        from src.version import get_upgrade_status

        return jsonify(get_upgrade_status())

    return app


if __name__ == "__main__":
    import sys

    # Check for --setup-only flag
    setup_only = "--setup-only" in sys.argv

    # Initialize the global last_known_chores before creating the app

    app = create_app()

    # Initialize PIR sensor (motion events reach the frontend via SSE)
    from src.pir_sensor.sensor import initialize_pir_sensor

    config = get_config()
    pir_pin = config.get("pir_sensor.gpio_pin", 18)
    pir_sensor = initialize_pir_sensor(pin=pir_pin)

    if not setup_only:
        # Start PIR monitoring if enabled
        if config.get("pir_sensor.enabled", True):
            from src.pir_sensor.sensor import start_pir_monitoring

            if start_pir_monitoring():
                logging.info("PIR sensor monitoring started")
            else:
                logging.warning("Failed to start PIR sensor monitoring")

        # Get app configuration
        debug_mode = config.get("app.debug", False)
        host = config.get(
            "app.host", "0.0.0.0"
        )  # nosec B104 # Intentional for family calendar local network access
        port = config.get("app.port", 5000)
        use_reloader = config.get("app.use_reloader", False)

        # Only use debug mode in development
        if config.is_production() and debug_mode:
            logging.warning(
                "Debug mode is enabled in production! Consider disabling it."
            )
            debug_mode = False  # Force disable in production

        # Ignore .db files to prevent reload loop caused by background updates
        app.run(
            host=host,
            port=port,
            debug=debug_mode,
            use_reloader=use_reloader,
            exclude_patterns=["**/*.db"],
        )
    else:
        logger.info("Setup completed. Exiting without starting server.")
