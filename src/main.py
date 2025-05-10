import datetime
import threading
from flask import Flask, redirect, url_for

# Import utility functions
from src.weather_integration.utils import get_weather_icon

# Shared resources across components
google_fetch_lock = threading.Lock()    # Global lock for Google API fetching
background_tasks = {}                   # Dict to track background task status by month/year
last_known_chores = []                  # Global variable to store the last known chores list


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
                    comparable_set.add((item.get('id'), item.get('title'), item.get('notes'), item.get('status')))
                else:
                    # Fallback to string representation
                    comparable_set.add(str(item))
            except Exception as e:
                print(f"Error making chore comparable: {e}")
                # Just ignore items we can't process
                pass
    return comparable_set


def create_app():
    """Application factory to create and configure the Flask app."""
    app = Flask(__name__)
    app.jinja_env.globals.update(get_weather_icon=get_weather_icon)
    
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
    from src.google_integration.routes import google_bp
    app.register_blueprint(calendar_bp)
    app.register_blueprint(slideshow_bp)
    app.register_blueprint(weather_bp)
    app.register_blueprint(chores_bp)
    app.register_blueprint(google_bp)
    
    @app.route('/')
    def index_redirect():
        """Redirects the base URL to the current month's calendar view."""
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        return redirect(url_for('calendar.view', year=now.year, month=now.month))
        
    return app


if __name__ == '__main__':
    # Initialize the global last_known_chores before creating the app
    # Can't use global in the top level of a module
    from src.google_integration.tasks_api import get_chores
    last_known_chores = get_chores()
    
    app = create_app()
    # Ignore .db files to prevent reload loop caused by background updates
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=True, exclude_patterns=["**/*.db"])
