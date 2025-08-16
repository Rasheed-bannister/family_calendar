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
    let visualIndicator = null;
    let statusIndicator = null;
    let motionFeedbackTimeout = null;
    let config = null;
    
    const STATUS_CHECK_INTERVAL = 5000; // Check status every 5 seconds
    const ACTIVITY_ENDPOINT = '/pir/activity';
    const STATUS_ENDPOINT = '/pir/status';
    const START_ENDPOINT = '/pir/start';
    const STOP_ENDPOINT = '/pir/stop';
    const EVENTS_ENDPOINT = '/pir/events';
    const TEST_ENDPOINT = '/pir/trigger_test';

    // Private methods
    function createVisualIndicators() {
        // Create motion detection indicator
        visualIndicator = document.createElement('div');
        visualIndicator.className = 'pir-motion-indicator';
        visualIndicator.innerHTML = '👁️ Motion Detected';
        visualIndicator.style.display = 'none';
        
        // Create status indicator
        statusIndicator = document.createElement('div');
        statusIndicator.className = 'pir-status-indicator';
        statusIndicator.innerHTML = '<span class="pir-icon">📡</span> <span class="pir-status-text">PIR Sensor</span>';
        
        // Add to page
        document.body.appendChild(visualIndicator);
        document.body.appendChild(statusIndicator);
        
        // Update status based on configuration
        updateStatusIndicator();
    }
    
    function updateStatusIndicator() {
        if (!statusIndicator) return;
        
        const statusText = statusIndicator.querySelector('.pir-status-text');
        const statusIcon = statusIndicator.querySelector('.pir-icon');
        
        if (isMonitoring) {
            statusIndicator.classList.add('active');
            statusIndicator.classList.remove('inactive', 'error');
            statusText.textContent = 'PIR Active';
            statusIcon.textContent = '👁️';
        } else if (isInitialized) {
            statusIndicator.classList.add('inactive');
            statusIndicator.classList.remove('active', 'error');
            statusText.textContent = 'PIR Standby';
            statusIcon.textContent = '⏸️';
        } else {
            statusIndicator.classList.add('error');
            statusIndicator.classList.remove('active', 'inactive');
            statusText.textContent = 'PIR Error';
            statusIcon.textContent = '❌';
        }
    }
    
    function showMotionFeedback() {
        if (!visualIndicator || !config?.show_pir_feedback) return;
        
        // Clear any existing timeout
        if (motionFeedbackTimeout) {
            clearTimeout(motionFeedbackTimeout);
        }
        
        // Show motion indicator with animation
        visualIndicator.style.display = 'block';
        visualIndicator.classList.add('motion-detected');
        
        // Create ripple effect
        const ripple = document.createElement('div');
        ripple.className = 'motion-ripple';
        document.body.appendChild(ripple);
        
        // Position ripple at center of screen
        const rect = document.body.getBoundingClientRect();
        ripple.style.left = (rect.width / 2) + 'px';
        ripple.style.top = (rect.height / 2) + 'px';
        
        // Trigger ripple animation
        setTimeout(() => {
            ripple.classList.add('ripple-animate');
        }, 10);
        
        // Hide after delay
        motionFeedbackTimeout = setTimeout(() => {
            visualIndicator.style.display = 'none';
            visualIndicator.classList.remove('motion-detected');
            
            // Remove ripple
            if (document.body.contains(ripple)) {
                document.body.removeChild(ripple);
            }
        }, 2000);
    }
    
    async function loadConfiguration() {
        try {
            // Try to load configuration from server
            const response = await fetch('/api/config');
            if (response.ok) {
                const fullConfig = await response.json();
                config = {
                    show_pir_feedback: fullConfig.ui?.show_pir_feedback ?? true,
                    animation_duration: fullConfig.ui?.animation_duration_ms ?? 300
                };
            } else {
                // Use defaults
                config = {
                    show_pir_feedback: true,
                    animation_duration: 300
                };
            }
        } catch (error) {
            console.warn('Could not load PIR configuration, using defaults:', error);
            config = {
                show_pir_feedback: true,
                animation_duration: 300
            };
        }
    }

    async function checkPIRStatus() {
        try {
            const response = await fetch(STATUS_ENDPOINT);
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            
            if (data.status === 'initialized' && data.monitoring !== isMonitoring) {
                isMonitoring = data.monitoring;
                updateStatusIndicator();
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
                    
                    // Show visual feedback
                    showMotionFeedback();
                    
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
            
            // Load configuration
            await loadConfiguration();
            
            // Create visual indicators
            createVisualIndicators();
            
            // Check initial status
            const status = await checkPIRStatus();
            if (!status) {
                console.warn('PIR sensor not available on backend');
                updateStatusIndicator(); // Show error state
                return false;
            }

            console.log('PIR sensor component initialized:', status);
            isInitialized = true;
            isMonitoring = status.monitoring;
            updateStatusIndicator();

            // Start monitoring if not already running
            if (!isMonitoring) {
                const started = await startPIRMonitoring();
                if (!started) {
                    console.warn('Failed to start PIR monitoring during initialization');
                }
                updateStatusIndicator();
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
