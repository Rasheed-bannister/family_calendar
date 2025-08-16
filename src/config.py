"""
Configuration management for Family Calendar application.
Loads settings from config.json with defaults and validation.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

class Config:
    """Configuration manager for the Family Calendar application."""
    
    # Default configuration values
    DEFAULTS = {
        "app": {
            "debug": False,
            "host": "0.0.0.0",
            "port": 5000,
            "secret_key": None,  # Should be set in config file
            "use_reloader": False,
            "environment": "production"  # production, development, testing
        },
        "weather": {
            "latitude": 40.759010,
            "longitude": -73.984474,
            "timezone": "America/New_York",
            "cache_duration": 600,  # seconds
            "offline_fallback": True
        },
        "pir_sensor": {
            "enabled": True,
            "gpio_pin": 18,
            "debounce_time": 2.0
        },
        "inactivity": {
            "day_timeout_minutes": 60,
            "night_timeout_seconds": 5,
            "day_brightness_reduction": 0.6,
            "night_brightness_reduction": 0.2,
            "night_start_hour": 21,
            "night_end_hour": 6,
            "slideshow_delay_seconds": 5
        },
        "google": {
            "sync_interval_minutes": 3,
            "max_retry_attempts": 3
        },
        "ui": {
            "show_loading_indicators": False,
            "show_pir_feedback": False,
            "enhanced_virtual_keyboard": True,
            "touch_optimized": True,
            "animation_duration_ms": 300
        },
        "paths": {
            "photos_dir": "src/static/photos",
            "credentials_dir": "src/google_integration"
        },
        "logging": {
            "level": "WARN",
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            "file": "calendar.log",
            "max_bytes": 10485760,  # 10MB
            "backup_count": 5
        }
    }
    
    def __init__(self, config_file: Optional[str] = None):
        """Initialize configuration from file or defaults."""
        self.config_file = config_file or self._find_config_file()
        self.config = self._load_config()
        self._validate_config()
        self._setup_logging()
        
    def _find_config_file(self) -> Path:
        """Find the configuration file in standard locations."""
        # Check multiple locations in order of preference
        locations = [
            Path.cwd() / "config.json",
            Path.home() / ".calendar" / "config.json",
            Path(__file__).parent.parent / "config.json",
            Path("/etc/calendar/config.json")
        ]
        
        for location in locations:
            if location.exists():
                logging.info(f"Found config file at: {location}")
                return location
        
        # If no config file exists, create a default one
        default_location = Path.cwd() / "config.json"
        logging.info(f"No config file found. Creating default at: {default_location}")
        self._create_default_config(default_location)
        return default_location
    
    def _create_default_config(self, path: Path):
        """Create a default configuration file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Generate a secret key for the default config
        import secrets
        default_config = self.DEFAULTS.copy()
        default_config["app"]["secret_key"] = secrets.token_hex(32)
        
        try:
            with open(path, 'w') as f:
                json.dump(default_config, f, indent=2)
        except (IOError, ValueError) as e:
            logging.error(f"Error creating default config file: {e}")
            return
        
        logging.info(f"Created default configuration file at: {path}")
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file with defaults as fallback."""
        config = self.DEFAULTS.copy()
        
        if self.config_file and Path(self.config_file).exists():
            try:
                with open(self.config_file, 'r') as f:
                    file_config = json.load(f)
                    # Deep merge with defaults
                    config = self._deep_merge(config, file_config)
                    logging.info(f"Loaded configuration from: {self.config_file}")
            except (ValueError, IOError) as e:
                logging.error(f"Error loading config file: {e}")
                logging.warning("Using default configuration")
        
        # Override with environment variables if present (for backwards compatibility)
        self._apply_env_overrides(config)
        
        return config
    
    def _deep_merge(self, base: Dict, override: Dict) -> Dict:
        """Deep merge two dictionaries."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result
    
    def _apply_env_overrides(self, config: Dict):
        """Apply environment variable overrides for backwards compatibility."""
        env_mappings = {
            'CALENDAR_WEATHER_LATITUDE': ('weather', 'latitude', float),
            'CALENDAR_WEATHER_LONGITUDE': ('weather', 'longitude', float),
            'CALENDAR_TIMEZONE': ('weather', 'timezone', str),
            'CALENDAR_DEBUG': ('app', 'debug', lambda x: x.lower() == 'true'),
            'CALENDAR_PORT': ('app', 'port', int),
            'CALENDAR_ENV': ('app', 'environment', str)
        }
        
        for env_var, (section, key, converter) in env_mappings.items():
            if env_var in os.environ:
                try:
                    config[section][key] = converter(os.environ[env_var])
                    logging.info(f"Override from environment: {env_var}")
                except (ValueError, KeyError) as e:
                    logging.error(f"Error applying environment override {env_var}: {e}")
    
    def _validate_config(self):
        """Validate configuration values."""
        errors = []
        
        # Validate required fields
        if not self.config['app'].get('secret_key'):
            import secrets
            self.config['app']['secret_key'] = secrets.token_hex(32)
            logging.warning("No secret key configured. Generated a random one.")
        
        # Validate numeric ranges
        if not 0 <= self.config['weather']['latitude'] <= 90:
            errors.append("Weather latitude must be between 0 and 90")
        
        if not -180 <= self.config['weather']['longitude'] <= 180:
            errors.append("Weather longitude must be between -180 and 180")
        
        if not 1 <= self.config['app']['port'] <= 65535:
            errors.append("Port must be between 1 and 65535")
        
        # Validate paths exist or can be created
        for path_key, path_value in self.config['paths'].items():
            if path_value and not Path(path_value).exists():
                try:
                    Path(path_value).mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    errors.append(f"Cannot create {path_key}: {e}")
        
        if errors:
            for error in errors:
                logging.error(f"Configuration error: {error}")
            raise ValueError(f"Configuration validation failed: {'; '.join(errors)}")
        
        logging.info("Configuration validation successful")
    
    def _setup_logging(self):
        """Configure logging based on settings."""
        log_config = self.config['logging']
        
        # Create logs directory if needed
        log_file = Path(log_config['file'])
        log_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Configure logging
        logging.basicConfig(
            level=getattr(logging, log_config['level']),
            format=log_config['format'],
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        
        # Add rotating file handler if specified
        if log_config.get('max_bytes'):
            from logging.handlers import RotatingFileHandler
            handler = RotatingFileHandler(
                log_file,
                maxBytes=log_config['max_bytes'],
                backupCount=log_config.get('backup_count', 5)
            )
            handler.setFormatter(logging.Formatter(log_config['format']))
            logging.getLogger().addHandler(handler)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value using dot notation."""
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def set(self, key: str, value: Any):
        """Set a configuration value using dot notation."""
        keys = key.split('.')
        target = self.config
        
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        
        target[keys[-1]] = value
    
    def save(self):
        """Save current configuration to file."""
        if self.config_file:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
            logging.info(f"Configuration saved to: {self.config_file}")
    
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.config['app']['environment'] == 'production'
    
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.config['app']['environment'] == 'development'
    
    def __getitem__(self, key: str) -> Any:
        """Allow dictionary-style access."""
        return self.config[key]
    
    def __contains__(self, key: str) -> bool:
        """Check if a key exists in config."""
        return key in self.config


# Global configuration instance
_config = None

def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config

def reload_config():
    """Reload configuration from file."""
    global _config
    _config = Config()
    return _config