import openmeteo_requests
import requests_cache
import pandas as pd
from retry_requests import retry
from datetime import datetime, timedelta
import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

# Import configuration
from src.config import get_config

# Cache file for offline mode
WEATHER_CACHE_FILE = Path(__file__).parent / "weather_cache.json"

def load_cached_weather() -> Optional[Dict[str, Any]]:
    """Load cached weather data for offline mode."""
    if WEATHER_CACHE_FILE.exists():
        try:
            with open(WEATHER_CACHE_FILE, 'r') as f:
                cache_data = json.load(f)
                # Check if cache is not too old (24 hours)
                cache_time = datetime.fromisoformat(cache_data.get('cached_at', ''))
                if datetime.now() - cache_time < timedelta(hours=24):
                    logging.info("Using cached weather data for offline mode")
                    # Deserialize datetime objects from cache
                    return _deserialize_from_cache(cache_data['data'])
        except (ValueError, KeyError) as e:
            logging.error(f"Error loading weather cache: {e}")
            # Remove corrupted cache file
            try:
                WEATHER_CACHE_FILE.unlink()
                logging.info("Removed corrupted weather cache file")
            except OSError:
                pass
        except Exception as e:
            logging.error(f"Unexpected error loading weather cache: {e}")
            # Remove corrupted cache file
            try:
                WEATHER_CACHE_FILE.unlink()
                logging.info("Removed corrupted weather cache file")
            except OSError:
                pass
    return None

def _serialize_for_cache(obj):
    """Convert datetime objects and other non-JSON-serializable objects to strings."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, (pd.Timestamp, pd.DatetimeIndex)):
        return obj.isoformat() if hasattr(obj, 'isoformat') else str(obj)
    elif isinstance(obj, dict):
        return {key: _serialize_for_cache(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [_serialize_for_cache(item) for item in obj]
    elif hasattr(obj, 'item'):  # numpy types
        return obj.item()
    elif hasattr(obj, 'tolist'):  # numpy arrays
        return obj.tolist()
    else:
        return obj

def _deserialize_from_cache(obj):
    """Convert ISO strings back to datetime objects where appropriate."""
    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            if key in ['time', 'sunrise', 'sunset', 'date'] and isinstance(value, str):
                try:
                    result[key] = datetime.fromisoformat(value)
                except ValueError:
                    result[key] = value
            else:
                result[key] = _deserialize_from_cache(value)
        return result
    elif isinstance(obj, list):
        return [_deserialize_from_cache(item) for item in obj]
    else:
        return obj

def save_weather_cache(data: Dict[str, Any]):
    """Save weather data to cache for offline use."""
    try:
        # Serialize datetime objects before caching
        serializable_data = _serialize_for_cache(data)
        
        cache_data = {
            'cached_at': datetime.now().isoformat(),
            'data': serializable_data
        }
        with open(WEATHER_CACHE_FILE, 'w') as f:
            json.dump(cache_data, f, indent=2)
    except (IOError, ValueError) as e:
        logging.error(f"Error saving weather cache: {e}")

def get_weather_data():
    """Fetches current weather and daily forecast from Open-Meteo API with offline support."""
    config = get_config()
    
    # Get location settings from configuration
    latitude = config.get('weather.latitude', 40.759010)
    longitude = config.get('weather.longitude', -73.984474)
    timezone = config.get('weather.timezone', 'America/New_York')
    cache_duration = config.get('weather.cache_duration', 300)
    offline_fallback = config.get('weather.offline_fallback', True)
    
    try:
        # Setup the Open-Meteo API client with cache and retry on error
        cache_session = requests_cache.CachedSession('.cache', expire_after=cache_duration)
        retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
        openmeteo = openmeteo_requests.Client(session=retry_session)
    
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

        # Prepare return data
        weather_data = {
            "current": current_data,
            "daily": daily_dataframe.to_dict(orient="records") # Convert dataframe to list of dicts
        }
        
        # Save to cache for offline use
        save_weather_cache(weather_data)
        
        return weather_data
        
    except Exception as e:
        logging.error(f"Error fetching weather data: {e}")
        
        # Try to use cached data if offline fallback is enabled
        if offline_fallback:
            cached_data = load_cached_weather()
            if cached_data:
                return cached_data
        
        # Return default/empty weather data as fallback
        logging.warning("Returning default weather data due to API failure")
        return {
            "current": {
                "time": datetime.now(),
                "apparent_temperature": 70,
                "is_day": 1,
                "weather_code": 0
            },
            "daily": []
        }
