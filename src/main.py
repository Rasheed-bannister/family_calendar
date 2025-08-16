import datetime
import threading
import logging
from flask import Flask, redirect, url_for

# Import configuration
from src.config import get_config

# Import utility functions
from src.weather_integration.utils import get_weather_icon

# Shared resources across components
google_fetch_lock = threading.Lock()    # Global lock for Google API fetching
background_tasks = {}                   # Dict to track background task status by month/year


def _make_chores_comparable(chores_list):
    """Creates a simplified, comparable representation of the chores list."""
    if not chores_list:
        return set() # Return empty set if there are no chores
        
    if not isinstance(chores_list, list):
        return None 
        
    comparable_set = set()
    for item in chores_list:
        if isinstance(item, dict):
            # Dictionary representation (from database)
            comparable_set.add((item.get('id'), item.get('title'), item.get('notes'), item.get('status')))
        else:
            # Likely a Chore object (from Google)
            try:
                # Try to access attributes that would be present on a Chore object
                if hasattr(item, 'id') and hasattr(item, 'title') and hasattr(item, 'notes') and hasattr(item, 'status'):
                    comparable_set.add((getattr(item, 'id'), getattr(item, 'title'), getattr(item, 'notes'), getattr(item, 'status')))
                else:
                    # Fallback to string representation
                    comparable_set.add(str(item))
            except Exception as e:
                print(f"Error making chore comparable: {e}")
                # Just ignore items we can't process
                pass
    return comparable_set


def clear_stale_background_tasks():
    """Clear any stale background tasks from previous runs."""
    global background_tasks
    with google_fetch_lock:
        # Clear all background tasks on startup to prevent stuck states
        background_tasks.clear()
        print("Cleared stale background tasks")

def create_app():
    """Application factory to create and configure the Flask app."""
    config = get_config()
    
    # Clear any stale background tasks from previous runs
    clear_stale_background_tasks()
    
    app = Flask(__name__)
    app.config['SECRET_KEY'] = config.get('app.secret_key')
    app.jinja_env.globals.update(get_weather_icon=get_weather_icon)
    
    # Initialize health monitoring
    from src.health_monitor import health_monitor
    
    # Set up global error handler for critical errors
    @app.errorhandler(500)
    def handle_500_error(error):
        health_monitor.record_error("Internal Server Error", str(error), is_critical=True)
        return "Internal Server Error", 500
    
    @app.errorhandler(Exception)
    def handle_exception(error):
        # Don't handle HTTP exceptions (like 404, 403) as critical
        if hasattr(error, 'code'):
            return error
        
        # Log unhandled exceptions as critical errors
        should_restart = health_monitor.record_error("Unhandled Exception", str(error), is_critical=True)
        
        if should_restart:
            logging.critical("Application restart threshold reached due to critical errors")
            # In a production environment, this could trigger a restart mechanism
            
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
    from src.slideshow.routes import slideshow_bp
    from src.weather_integration.routes import weather_bp
    from src.chores_app.routes import chores_bp
    from src.google_integration import google_bp
    from src.pir_sensor.routes import pir_bp
    from src.health_routes import health_bp
    from src.photo_upload.routes import upload_bp
    from src.photo_upload.auth import init_token_manager
    
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
    
    @app.route('/')
    def index_redirect():
        """Redirects the base URL to the current month's calendar view."""
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        return redirect(url_for('calendar.view', year=now.year, month=now.month))
    
    @app.route('/api/config')
    def get_config_api():
        """API endpoint to get configuration data."""
        from flask import jsonify
        config = get_config()
        return jsonify(config.config)
        
    return app


if __name__ == '__main__':
    import sys
    
    # Check for --setup-only flag
    setup_only = '--setup-only' in sys.argv
    
    # Initialize the global last_known_chores before creating the app
    
    app = create_app()
    
    # Initialize PIR sensor with activity callback
    from src.pir_sensor.sensor import initialize_pir_sensor
    
    def on_motion_detected():
        """Callback function when PIR sensor detects motion"""
        logging.info("Motion detected - activity registered")
        # The frontend will handle the actual activity registration
        # This is just for backend logging
    
    config = get_config()
    pir_pin = config.get('pir_sensor.gpio_pin', 18)
    pir_sensor = initialize_pir_sensor(pin=pir_pin, callback=on_motion_detected)
    
    if not setup_only:
        # Start PIR monitoring if enabled
        if config.get('pir_sensor.enabled', True):
            from src.pir_sensor.sensor import start_pir_monitoring
            if start_pir_monitoring():
                logging.info("PIR sensor monitoring started")
            else:
                logging.warning("Failed to start PIR sensor monitoring")
        
        # Get app configuration
        debug_mode = config.get('app.debug', False)
        host = config.get('app.host', '0.0.0.0')
        port = config.get('app.port', 5000)
        use_reloader = config.get('app.use_reloader', False)
        
        # Only use debug mode in development
        if config.is_production() and debug_mode:
            logging.warning("Debug mode is enabled in production! Consider disabling it.")
            debug_mode = False  # Force disable in production
        
        # Ignore .db files to prevent reload loop caused by background updates
        app.run(
            host=host, 
            port=port, 
            debug=debug_mode, 
            use_reloader=use_reloader, 
            exclude_patterns=["**/*.db"]
        )
    else:
        print("Setup completed. Exiting without starting server.")
