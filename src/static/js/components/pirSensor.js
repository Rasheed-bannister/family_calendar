/**
 * PIR Sensor Component
 * Handles PIR sensor integration and activity detection for the calendar application
 */
const PIRSensor = (function() {
    // Private variables
    let isInitialized = false;
    let isMonitoring = false;
    let statusCheckInterval = null;
    let activityCallback = null;
    let eventSource = null;
    const STATUS_CHECK_INTERVAL = 5000; // Check status every 5 seconds
    const ACTIVITY_ENDPOINT = '/pir/activity';
    const STATUS_ENDPOINT = '/pir/status';
    const START_ENDPOINT = '/pir/start';
    const STOP_ENDPOINT = '/pir/stop';
    const EVENTS_ENDPOINT = '/pir/events';
    const TEST_ENDPOINT = '/pir/trigger_test';

    // Private methods
    async function checkPIRStatus() {
        try {
            const response = await fetch(STATUS_ENDPOINT);
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            
            if (data.status === 'initialized' && data.monitoring !== isMonitoring) {
                isMonitoring = data.monitoring;
                console.log(`PIR sensor monitoring status changed: ${isMonitoring ? 'started' : 'stopped'}`);
            }
            
            return data;
        } catch (error) {
            console.error('Error checking PIR sensor status:', error);
            return null;
        }
    }

    async function startPIRMonitoring() {
        try {
            const response = await fetch(START_ENDPOINT, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                }
            });
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            
            if (data.success) {
                isMonitoring = true;
                console.log('PIR sensor monitoring started successfully');
                return true;
            } else {
                console.error('Failed to start PIR monitoring:', data.message);
                return false;
            }
        } catch (error) {
            console.error('Error starting PIR monitoring:', error);
            return false;
        }
    }

    async function stopPIRMonitoring() {
        try {
            const response = await fetch(STOP_ENDPOINT, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                }
            });
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            
            if (data.success) {
                isMonitoring = false;
                console.log('PIR sensor monitoring stopped successfully');
                return true;
            } else {
                console.error('Failed to stop PIR monitoring:', data.message);
                return false;
            }
        } catch (error) {
            console.error('Error stopping PIR monitoring:', error);
            return false;
        }
    }

    function startStatusChecking() {
        if (statusCheckInterval) return;
        
        statusCheckInterval = setInterval(async () => {
            const status = await checkPIRStatus();
            if (status && status.status === 'initialized' && !status.monitoring && isInitialized) {
                // Try to restart monitoring if it stopped unexpectedly
                console.log('PIR monitoring stopped unexpectedly, attempting to restart...');
                await startPIRMonitoring();
            }
        }, STATUS_CHECK_INTERVAL);
    }

    function stopStatusChecking() {
        if (statusCheckInterval) {
            clearInterval(statusCheckInterval);
            statusCheckInterval = null;
        }
    }

    function startEventStream() {
        if (eventSource) return;

        eventSource = new EventSource(EVENTS_ENDPOINT);
        
        eventSource.onmessage = function(event) {
            try {
                const data = JSON.parse(event.data);
                
                if (data.type === 'motion_detected') {
                    console.log('PIR motion detected via SSE');
                    
                    // Trigger the activity callback
                    if (activityCallback && typeof activityCallback === 'function') {
                        activityCallback('motion');
                    }
                } else if (data.type === 'heartbeat') {
                    // Heartbeat to keep connection alive
                }
            } catch (error) {
                console.error('Error parsing PIR SSE event:', error);
            }
        };
        
        eventSource.onerror = function(error) {
            console.error('PIR SSE connection error:', error);
            
            // Try to reconnect after a delay
            setTimeout(() => {
                if (isInitialized && !eventSource) {
                    startEventStream();
                }
            }, 5000);
        };
        
        console.log('PIR sensor event stream started');
    }

    function stopEventStream() {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
            console.log('PIR sensor event stream stopped');
        }
    }

    // Public methods
    const publicAPI = {
        init: async function(callback = null) {
            if (isInitialized) {
                console.log('PIR sensor already initialized');
                return true;
            }

            activityCallback = callback;
            
            // Check initial status
            const status = await checkPIRStatus();
            if (!status) {
                console.warn('PIR sensor not available on backend');
                return false;
            }

            console.log('PIR sensor component initialized:', status);
            isInitialized = true;
            isMonitoring = status.monitoring;

            // Start monitoring if not already running
            if (!isMonitoring) {
                const started = await startPIRMonitoring();
                if (!started) {
                    console.warn('Failed to start PIR monitoring during initialization');
                }
            }

            // Start periodic status checking
            startStatusChecking();
            
            // Start event stream for real-time motion detection
            startEventStream();

            return true;
        },

        start: async function() {
            if (!isInitialized) {
                console.error('PIR sensor not initialized');
                return false;
            }

            return await startPIRMonitoring();
        },

        stop: async function() {
            if (!isInitialized) {
                console.error('PIR sensor not initialized');
                return false;
            }

            return await stopPIRMonitoring();
        },

        setActivityCallback: function(callback) {
            activityCallback = callback;
        },

        reportActivity: async function(activityType = 'motion') {
            if (!isInitialized) {
                console.warn('PIR sensor not initialized, cannot report activity');
                return false;
            }

            try {
                // Report activity to backend
                await fetch(ACTIVITY_ENDPOINT, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ type: activityType })
                });

                // Trigger local activity callback
                if (activityCallback && typeof activityCallback === 'function') {
                    activityCallback(activityType);
                }

                console.log(`PIR activity reported: ${activityType}`);
                return true;
            } catch (error) {
                console.error('Error reporting PIR activity:', error);
                return false;
            }
        },

        getStatus: function() {
            return {
                initialized: isInitialized,
                monitoring: isMonitoring
            };
        },

        triggerTestMotion: async function() {
            if (!isInitialized) {
                console.warn('PIR sensor not initialized');
                return false;
            }

            try {
                const response = await fetch(TEST_ENDPOINT, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    }
                });

                if (response.ok) {
                    console.log('Test motion triggered successfully');
                    return true;
                } else {
                    console.error('Failed to trigger test motion');
                    return false;
                }
            } catch (error) {
                console.error('Error triggering test motion:', error);
                return false;
            }
        },

        cleanup: function() {
            stopStatusChecking();
            stopEventStream();
            if (isInitialized && isMonitoring) {
                stopPIRMonitoring();
            }
            isInitialized = false;
            isMonitoring = false;
            activityCallback = null;
        }
    };

    return publicAPI;
})();

export default PIRSensor;
