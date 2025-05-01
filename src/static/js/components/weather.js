/**
 * Weather Component
 * Handles weather display and updates
 */
const Weather = (function() {
    // Private variables
    let weatherContainer;
    let weatherUpdateTimer = null;
    const WEATHER_UPDATE_INTERVAL = 300000; // Check for weather updates every 5 minutes (300000ms)
    let lastWeatherUpdate = new Date().getTime();
    
    // Private methods
    function applyWeatherGradient() {
        const currentWeatherDiv = document.querySelector('.current-weather');
        if (currentWeatherDiv && currentWeatherDiv.dataset.isDay !== undefined) {
            // Convert various possible values to a boolean
            // The Open-Meteo API uses numeric 0 and 1, which need to be properly handled
            const rawValue = currentWeatherDiv.dataset.isDay;
            
            // Handle all possible values: 1, "1", true, "true", or any non-zero number
            const isDay = rawValue === 1 || 
                         rawValue === "1" || 
                         rawValue.toLowerCase() === "true" ||
                         (parseInt(rawValue, 10) && parseInt(rawValue, 10) !== 0);
            
            currentWeatherDiv.classList.remove('day-gradient', 'night-gradient');
            if (isDay) {
                currentWeatherDiv.classList.add('day-gradient');
            } else {
                currentWeatherDiv.classList.add('night-gradient');
            }
        }
    }

    function updateWeatherData() {
        console.log("Checking for weather updates...");
        
        fetch('/api/weather-update')
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.text();
            })
            .then(html => {
                // The response is the weather fragment HTML
                const currentWeatherContainer = document.querySelector('.weather-container');
                if (currentWeatherContainer) {
                    currentWeatherContainer.outerHTML = html;
                    console.log("Weather data updated successfully");
                    
                    // Apply the weather gradient to the new container
                    applyWeatherGradient();
                    
                    // Update timestamp
                    lastWeatherUpdate = new Date().getTime();
                }
            })
            .catch(error => {
                console.error("Error updating weather data:", error);
            });
    }

    function startWeatherUpdateTimer() {
        // Clear any existing timer
        if (weatherUpdateTimer) {
            clearInterval(weatherUpdateTimer);
        }
        
        // Set interval to check for weather updates
        weatherUpdateTimer = setInterval(updateWeatherData, WEATHER_UPDATE_INTERVAL);
        console.log(`Started weather update timer (checking every ${WEATHER_UPDATE_INTERVAL/60000} minutes)`);
    }

    function setupEventListeners() {
        // Handle page visibility changes to manage weather updates
        document.addEventListener('visibilitychange', function() {
            if (document.hidden) {
                // Page is hidden, pause weather updates
                if (weatherUpdateTimer) {
                    clearInterval(weatherUpdateTimer);
                    weatherUpdateTimer = null;
                }
                console.log("Page hidden, paused weather updates");
            } else {
                // Page is visible again, resume weather updates
                // Do an immediate check if it's been more than 5 minutes
                const currentTime = new Date().getTime();
                if (currentTime - lastWeatherUpdate > WEATHER_UPDATE_INTERVAL) {
                    updateWeatherData(); // Immediate update if it's been a while
                }
                startWeatherUpdateTimer();
                console.log("Page visible, resumed weather updates");
            }
        });
    }

    // Public methods
    return {
        init: function() {
            weatherContainer = document.querySelector('.weather-container');
            if (!weatherContainer) {
                console.error("Weather component: weather-container element not found!");
                return false;
            }
            
            applyWeatherGradient(); // Apply initial weather gradient
            startWeatherUpdateTimer(); // Start checking for weather updates
            setupEventListeners();
            
            return true;
        },
        
        pause: function() {
            if (weatherUpdateTimer) {
                clearInterval(weatherUpdateTimer);
                weatherUpdateTimer = null;
            }
        },
        
        resume: function() {
            const currentTime = new Date().getTime();
            if (currentTime - lastWeatherUpdate > WEATHER_UPDATE_INTERVAL) {
                updateWeatherData(); // Immediate update if it's been a while
            }
            startWeatherUpdateTimer();
        },
        
        forceUpdate: function() {
            updateWeatherData();
        }
    };
})();

export default Weather;