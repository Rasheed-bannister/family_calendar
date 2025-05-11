/**
 * Main Application
 * Initializes and coordinates all components
 */
import Calendar from './components/calendar.js';
import DailyView from './components/dailyView.js';
import Weather from './components/weather.js';
import Slideshow from './components/slideshow.js';
import Chores from './components/chores.js';
import Modal from './components/modal.js';
import VirtualKeyboard from './components/virtualKeyboard.js';

document.addEventListener('DOMContentLoaded', function() {
    console.log("Calendar application initializing...");
    
    // Initialize all components
    const componentsStatus = {
        modal: Modal.init(), // This initializes the event modal
        addChoreModal: Modal.initAddChoreModal ? Modal.initAddChoreModal() : true, 
        calendar: Calendar.init(),
        dailyView: DailyView.init(),
        weather: Weather.init(),
        slideshow: Slideshow.init(),
        chores: Chores.init(),
        virtualKeyboard: VirtualKeyboard.init() // Initialize the virtual keyboard
    };
    
    // Check if all components initialized successfully
    const failedComponents = Object.entries(componentsStatus)
        .filter(([name, status]) => !status)
        .map(([name]) => name);
    
    if (failedComponents.length > 0) {
        console.error(`Failed to initialize components: ${failedComponents.join(', ')}`);
    } else {
        console.log("All components initialized successfully");
    }
    
    // Activity tracking variables
    let lastActivityTimestamp = Date.now();
    const DAY_INACTIVITY_TIMEOUT = 60 * 60 * 1000; // 1 hour during daytime
    const NIGHT_INACTIVITY_TIMEOUT = 5 * 1000;     // 5 seconds at night
    const DAY_BRIGHTNESS_REDUCTION = 0.6;          // 40% reduction (multiply by 0.6)
    const NIGHT_BRIGHTNESS_REDUCTION = 0.2;        // 80% reduction (multiply by 0.2)
    const NIGHT_START_HOUR = 21;                   // 9:00 PM
    const NIGHT_END_HOUR = 6;                      // 6:00 AM
    let currentInactivityMode = 'none';            // 'none', 'day-inactive', 'night-inactive'
    let longInactivityMode = false;                // Track if we're in long inactivity mode
    let inactivityCheckInterval = null;
    let lastMovementTime = 0;
    const MOVEMENT_THROTTLE = 1000;                // Only register movement once per second
    const DEBUG_MODE = false;                      // Set to false in production
    
    // Create stylesheet for brightness control
    const createBrightnessStylesheet = function() {
        const styleElement = document.createElement('style');
        styleElement.id = 'brightness-control-style';
        document.head.appendChild(styleElement);
        return styleElement.sheet;
    };
    
    const brightnessStylesheet = createBrightnessStylesheet();
    
    // Function to check if it's night time
    function isNightTime() {
        const now = new Date();
        const hour = now.getHours();
        
        // Between 9 PM and 6 AM is considered night
        return hour >= NIGHT_START_HOUR || hour < NIGHT_END_HOUR;
    }
    
    // Function to get the appropriate timeout based on time of day
    function getCurrentInactivityTimeout() {
        return isNightTime() ? NIGHT_INACTIVITY_TIMEOUT : DAY_INACTIVITY_TIMEOUT;
    }
    
    // Function to get brightness reduction based on time of day
    function getCurrentBrightnessReduction() {
        return isNightTime() ? NIGHT_BRIGHTNESS_REDUCTION : DAY_BRIGHTNESS_REDUCTION;
    }
    
    // Function to register any user activity
    function registerActivity(type = 'generic') {
        const now = Date.now();
        lastActivityTimestamp = now;
        
        // Log activity in debug mode
        if (DEBUG_MODE) {
            console.log(`Activity detected: ${type} at ${new Date(now).toLocaleTimeString()}`);
        }
        
        // If we were in any inactivity mode, exit it now
        if (currentInactivityMode !== 'none') {
            exitInactivityMode();
        }
    }
    
    // Function to apply brightness reduction
    function applyBrightnessReduction(brightnessLevel) {
        // Clear existing rules
        while(brightnessStylesheet.cssRules.length > 0) {
            brightnessStylesheet.deleteRule(0);
        }
        
        // Add new rule
        brightnessStylesheet.insertRule(`
            body::after {
                content: "";
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background-color: rgba(0, 0, 0, ${1 - brightnessLevel});
                pointer-events: none;
                z-index: 9999;
                transition: background-color 1s ease;
            }
        `, 0);
    }
    
    // Function to enter appropriate inactivity mode based on time of day
    function enterInactivityMode() {
        const isNight = isNightTime();
        const newMode = isNight ? 'night-inactive' : 'day-inactive';
        
        if (currentInactivityMode === newMode) return; // Already in this mode
        
        const brightness = getCurrentBrightnessReduction();
        console.log(`Entering ${isNight ? 'night' : 'day'} inactivity mode (brightness: ${brightness * 100}%)`);
        currentInactivityMode = newMode;
        
        // Add class to body for CSS styling
        document.body.classList.add('reduced-brightness-mode');
        document.body.classList.add(currentInactivityMode);
        
        // Apply the brightness reduction
        applyBrightnessReduction(brightness);
        
        // If we're entering long inactivity mode (after a long period)
        if (isNight && Date.now() - lastActivityTimestamp > DAY_INACTIVITY_TIMEOUT) {
            enterLongInactivityMode();
        }
        
        // Display notification if in debug mode
        if (DEBUG_MODE) {
            showDebugNotification(`Entered ${isNight ? 'night' : 'day'} inactivity mode`);
        }
    }
    
    // Function to exit inactivity mode when activity is detected
    function exitInactivityMode() {
        if (currentInactivityMode === 'none') return; // Not in any inactivity mode
        
        console.log("Exiting inactivity mode");
        
        // Remove classes from body
        document.body.classList.remove('reduced-brightness-mode');
        document.body.classList.remove(currentInactivityMode);
        currentInactivityMode = 'none';
        
        // Remove the brightness filter
        applyBrightnessReduction(1.0); // Full brightness
        
        // If we were in long inactivity mode, exit that too
        if (longInactivityMode) {
            exitLongInactivityMode();
        }
        
        // Display notification if in debug mode
        if (DEBUG_MODE) {
            showDebugNotification("Exited inactivity mode");
        }
    }
    
    // Function to enter long inactivity mode after period of no activity
    function enterLongInactivityMode() {
        if (longInactivityMode) return; // Already in this mode
        
        console.log("Entering long inactivity mode (inactive for timeout period)");
        longInactivityMode = true;
        
        // Add class to body for CSS styling
        document.body.classList.add('long-inactivity-mode');
        
        // Pause components that need live updates
        Calendar.pause();
        Weather.pause();
        DailyView.pause();
        Chores.pause();
        
        // Keep slideshow running
        Slideshow.start();
        
        // Display notification if in debug mode
        if (DEBUG_MODE) {
            showDebugNotification("Entered inactivity mode");
        }
    }
    
    // Function to exit long inactivity mode when activity is detected
    function exitLongInactivityMode() {
        if (!longInactivityMode) return; // Not in this mode
        
        console.log("Exiting long inactivity mode");
        longInactivityMode = false;
        
        // Remove class from body
        document.body.classList.remove('long-inactivity-mode');
        
        // Resume components
        Calendar.resume();
        Weather.resume();
        DailyView.resume();
        Chores.resume();
        
        // Display notification if in debug mode
        if (DEBUG_MODE) {
            showDebugNotification("Exited inactivity mode");
        }
    }
    
    // Show debug notification
    function showDebugNotification(message) {
        const notification = document.createElement('div');
        notification.classList.add('debug-notification');
        notification.textContent = message;
        
        // Style the notification
        Object.assign(notification.style, {
            position: 'fixed',
            top: '10px',
            right: '10px',
            backgroundColor: 'rgba(0, 0, 0, 0.7)',
            color: 'white',
            padding: '10px',
            borderRadius: '4px',
            zIndex: '9999',
            fontSize: '14px'
        });
        
        document.body.appendChild(notification);
        
        // Remove after 3 seconds
        setTimeout(() => {
            if (document.body.contains(notification)) {
                document.body.removeChild(notification);
            }
        }, 3000);
    }
    
    // Show time until inactivity if in debug mode
    function updateDebugInfo() {
        if (!DEBUG_MODE) return;
        
        let debugElement = document.getElementById('activity-debug-info');
        
        if (!debugElement) {
            debugElement = document.createElement('div');
            debugElement.id = 'activity-debug-info';
            
            // Style the debug element
            Object.assign(debugElement.style, {
                position: 'fixed',
                bottom: '10px',
                right: '10px',
                backgroundColor: 'rgba(0, 0, 0, 0.7)',
                color: 'white',
                padding: '10px',
                borderRadius: '4px',
                zIndex: '9999',
                fontSize: '14px'
            });
            
            document.body.appendChild(debugElement);
        }
        
        // Calculate time until inactivity
        const currentTimeout = getCurrentInactivityTimeout();
        const timeSinceActivity = Date.now() - lastActivityTimestamp;
        const timeUntilInactivity = Math.max(0, currentTimeout - timeSinceActivity);
        const secondsUntilInactivity = Math.ceil(timeUntilInactivity / 1000);
        
        debugElement.innerHTML = `
            <div>Activity Debug:</div>
            <div>Time Mode: ${isNightTime() ? 'Night' : 'Day'}</div>
            <div>Inactivity Mode: ${currentInactivityMode}</div>
            <div>Long Inactivity: ${longInactivityMode ? 'Yes' : 'No'}</div>
            <div>Seconds until inactive: ${secondsUntilInactivity}</div>
            <div>Last activity: ${new Date(lastActivityTimestamp).toLocaleTimeString()}</div>
            <div><button id="test-inactive-day">Test Day Inactive</button></div>
            <div><button id="test-inactive-night">Test Night Inactive</button></div>
            <div><button id="test-inactive-long">Test Long Inactive</button></div>
        `;
        
        // Add event listeners to test buttons
        const testDayButton = document.getElementById('test-inactive-day');
        if (testDayButton) {
            testDayButton.addEventListener('click', function(e) {
                e.stopPropagation(); // Prevent this from registering as activity
                
                if (currentInactivityMode === 'day-inactive') {
                    exitInactivityMode();
                } else {
                    currentInactivityMode = 'none';
                    document.body.classList.remove('night-inactive');
                    applyBrightnessReduction(DAY_BRIGHTNESS_REDUCTION);
                    document.body.classList.add('day-inactive');
                    document.body.classList.add('reduced-brightness-mode');
                    currentInactivityMode = 'day-inactive';
                }
            });
        }
        
        const testNightButton = document.getElementById('test-inactive-night');
        if (testNightButton) {
            testNightButton.addEventListener('click', function(e) {
                e.stopPropagation(); // Prevent this from registering as activity
                
                if (currentInactivityMode === 'night-inactive') {
                    exitInactivityMode();
                } else {
                    currentInactivityMode = 'none';
                    document.body.classList.remove('day-inactive');
                    applyBrightnessReduction(NIGHT_BRIGHTNESS_REDUCTION);
                    document.body.classList.add('night-inactive');
                    document.body.classList.add('reduced-brightness-mode');
                    currentInactivityMode = 'night-inactive';
                }
            });
        }
        
        const testLongButton = document.getElementById('test-inactive-long');
        if (testLongButton) {
            testLongButton.addEventListener('click', function(e) {
                e.stopPropagation(); // Prevent this from registering as activity
                
                if (longInactivityMode) {
                    exitLongInactivityMode();
                } else {
                    enterLongInactivityMode();
                }
            });
        }
    }
    
    // Set up event listeners for various forms of user activity
    function setupActivityTracking() {
        // Mouse movement (throttled)
        document.addEventListener('mousemove', function(e) {
            const now = Date.now();
            // Only register movement if it's been longer than the throttle time
            if (now - lastMovementTime > MOVEMENT_THROTTLE) {
                lastMovementTime = now;
                registerActivity('mousemove');
            }
        });
        
        // Mouse clicks
        document.addEventListener('click', function() {
            registerActivity('click');
        });
        
        // Key presses (will work with IR sensor that simulates key press)
        document.addEventListener('keydown', function(e) {
            registerActivity('keydown: ' + e.key);
        });
        
        // Touch events for touchscreens
        document.addEventListener('touchstart', function() {
            registerActivity('touchstart');
        });
        
        document.addEventListener('touchmove', function() {
            const now = Date.now();
            // Throttle touch moves like mouse movements
            if (now - lastMovementTime > MOVEMENT_THROTTLE) {
                lastMovementTime = now;
                registerActivity('touchmove');
            }
        });
        
        // Start interval to check for inactivity
        inactivityCheckInterval = setInterval(() => {
            const currentTime = Date.now();
            const currentTimeout = getCurrentInactivityTimeout();
            
            // Check if the activity timeout has been reached
            if (currentTime - lastActivityTimestamp > currentTimeout) {
                // Check if we need to enter inactivity mode
                if (currentInactivityMode === 'none') {
                    enterInactivityMode();
                }
                
                // Check if we should enter long inactivity mode (based on day timeout)
                if (!longInactivityMode && currentTime - lastActivityTimestamp > DAY_INACTIVITY_TIMEOUT) {
                    enterLongInactivityMode();
                }
            }
            
            // Update debug info if enabled
            if (DEBUG_MODE) {
                updateDebugInfo();
            }
        }, 500); // Check every half second for more responsive changes
        
        console.log(`Activity tracking started (day timeout: ${DAY_INACTIVITY_TIMEOUT/1000}s, night timeout: ${NIGHT_INACTIVITY_TIMEOUT/1000}s)`);
    }
    
    // Initialize activity tracking
    setupActivityTracking();
    
    console.log("Calendar application initialized");
});

// Chore polling mechanism
const CHORE_POLLING_INTERVAL = 30000; // 30 seconds: How often to trigger a full refresh cycle
const CHORE_CHECK_UPDATE_INTERVAL = 5000; // 5 seconds: How often to check status after triggering
let isCheckingChoreUpdates = false; // Flag to prevent overlapping check loops

async function triggerChoresRefresh() {
    if (isCheckingChoreUpdates) {
        return;
    }
    isCheckingChoreUpdates = true;

    try {
        const response = await fetch('/chores/refresh', { method: 'POST' }); // Corrected endpoint and added POST method
        if (response.ok) {
            setTimeout(checkChoresUpdatesLoop, CHORE_CHECK_UPDATE_INTERVAL); // Start checking status
        } else {
            console.error('Chores: Failed to trigger refresh. Status:', response.status);
            isCheckingChoreUpdates = false;
            setTimeout(triggerChoresRefresh, CHORE_POLLING_INTERVAL); // Retry full cycle later
        }
    } catch (error) {
        console.error('Chores: Error during triggerChoresRefresh:', error);
        isCheckingChoreUpdates = false;
        setTimeout(triggerChoresRefresh, CHORE_POLLING_INTERVAL); // Retry full cycle later
    }
}

async function checkChoresUpdatesLoop() {
    const now = new Date();
    const year = now.getFullYear();
    const month = now.getMonth() + 1; // JavaScript months are 0-indexed

    try {
        const response = await fetch(`/calendar/check-updates/${year}/${month}`); // Ensure this path is correct
        if (!response.ok) {
            console.error('Chores: Failed to check for updates. Status:', response.status);
            isCheckingChoreUpdates = false;
            setTimeout(triggerChoresRefresh, CHORE_POLLING_INTERVAL);
            return;
        }

        const data = await response.json();

        if (data.chores_status === 'running') {
            setTimeout(checkChoresUpdatesLoop, CHORE_CHECK_UPDATE_INTERVAL);
        } else if (data.chores_status === 'complete') {
            isCheckingChoreUpdates = false;
            if (data.chores_changed) {
                console.log('Chores: Changes detected. Reloading page.');
                window.location.reload();
            } else {
                setTimeout(triggerChoresRefresh, CHORE_POLLING_INTERVAL); // Schedule next full cycle
            }
        } else if (data.chores_status === 'error') {
            console.error('Chores: Refresh completed with an error.');
            isCheckingChoreUpdates = false;
            setTimeout(triggerChoresRefresh, CHORE_POLLING_INTERVAL); // Schedule next full cycle
        } else {
            isCheckingChoreUpdates = false;
            setTimeout(triggerChoresRefresh, CHORE_POLLING_INTERVAL); // Schedule next full cycle
        }
    } catch (error) {
        console.error('Chores: Error during checkChoresUpdatesLoop:', error);
        isCheckingChoreUpdates = false;
        setTimeout(triggerChoresRefresh, CHORE_POLLING_INTERVAL); // Schedule next full cycle
    }
}

function initChoresPolling() {
    console.log('Chores: Initializing polling mechanism.');
    triggerChoresRefresh(); // Start the first refresh cycle
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initChoresPolling);
} else {
    initChoresPolling(); // DOMContentLoaded has already fired
}