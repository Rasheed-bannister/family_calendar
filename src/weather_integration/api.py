import openmeteo_requests
import requests_cache
import pandas as pd
from retry_requests import retry
from datetime import datetime
import os

def get_weather_data():
    """Fetches current weather and daily forecast from Open-Meteo API."""
    # Setup the Open-Meteo API client with cache and retry on error
    cache_session = requests_cache.CachedSession('.cache', expire_after=300)
    retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
    openmeteo = openmeteo_requests.Client(session=retry_session)

    # Get location settings from environment variables, with default fallbacks
    latitude = float(os.environ.get('CALENDAR_WEATHER_LATITUDE', '40.759010'))
    longitude = float(os.environ.get('CALENDAR_WEATHER_LONGITUDE', '-73.984474'))
    timezone = os.environ.get('CALENDAR_TIMEZONE', 'America/New_York')
    
    # Make sure all required weather variables are listed here
    # The order of variables in hourly or daily is important to assign them correctly below
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": ["weather_code", "apparent_temperature_max", "apparent_temperature_min", "sunrise", "sunset", "precipitation_probability_max"],
        "models": "best_match",
        "current": ["apparent_temperature", "is_day", "weather_code"],
        "timezone": timezone,
        "wind_speed_unit": "mph",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch"
    }
    responses = openmeteo.weather_api(url, params=params)

    # Process first location. Add a for-loop for multiple locations or weather models
    response = responses[0]

    # Current values. The order of variables needs to be the same as requested.
    current = response.Current()
    current_data = {
        "time": datetime.fromtimestamp(current.Time()), # Convert timestamp to datetime
        "apparent_temperature": current.Variables(0).Value(),
        "is_day": current.Variables(1).Value(),
        "weather_code": current.Variables(2).Value()
    }

    # Process daily data. The order of variables needs to be the same as requested.
    daily = response.Daily()
    daily_data = {"date": pd.date_range(
        start=pd.to_datetime(daily.Time(), unit="s", utc=True),
        end=pd.to_datetime(daily.TimeEnd(), unit="s", utc=True),
        freq=pd.Timedelta(seconds=daily.Interval()),
        inclusive="left"
    )}
    daily_data["weather_code"] = daily.Variables(0).ValuesAsNumpy()
    daily_data["apparent_temperature_max"] = daily.Variables(1).ValuesAsNumpy()
    daily_data["apparent_temperature_min"] = daily.Variables(2).ValuesAsNumpy()
    # Convert sunrise/sunset timestamps to datetime objects
    daily_data["sunrise"] = [datetime.fromtimestamp(ts) for ts in daily.Variables(3).ValuesInt64AsNumpy()]
    daily_data["sunset"] = [datetime.fromtimestamp(ts) for ts in daily.Variables(4).ValuesInt64AsNumpy()]
    daily_data["precipitation_probability_max"] = daily.Variables(5).ValuesAsNumpy()

    daily_dataframe = pd.DataFrame(data=daily_data)

    # Return data as a dictionary
    return {
        "current": current_data,
        "daily": daily_dataframe.to_dict(orient="records") # Convert dataframe to list of dicts
    }
