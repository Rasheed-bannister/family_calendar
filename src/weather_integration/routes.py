from flask import Blueprint, jsonify, render_template

from .api import get_weather_data

weather_bp = Blueprint("weather", __name__, url_prefix="/api")


@weather_bp.route("/weather-update")
def weather_update():
    """API endpoint to get fresh weather data, bypassing any internal cache."""
    try:
        weather_data = get_weather_data()

        if weather_data and weather_data.get("current") and weather_data.get("daily"):
            return render_template("components/weather.html", weather=weather_data)
        else:
            return jsonify({"error": "Could not fetch valid weather data"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
