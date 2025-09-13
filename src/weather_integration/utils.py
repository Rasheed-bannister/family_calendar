def get_weather_icon(code):
    """Maps WMO weather code to an emoji icon."""
    if code == 0:
        return "☀️"  # Clear sky
    elif code in [1, 2]:
        return "🌤️"  # Mainly clear, partly cloudy
    elif code == 3:
        return "☁️"  # Overcast
    elif code in [45, 48]:
        return "🌫️"  # Fog
    elif code in [51, 53, 55, 61, 63, 65, 80, 81, 82]:
        return "🌧️"  # Drizzle, Rain, Showers
    elif code in [56, 57, 66, 67]:
        return "🥶"  # Freezing Drizzle/Rain - Using a cold face, adjust as needed
    elif code in [71, 73, 75, 77, 85, 86]:
        return "❄️"  # Snowfall, Snow grains, Snow showers
    elif code in [95, 96, 99]:
        return "⛈️"  # Thunderstorm
    else:
        return "❓"  # Unknown code
