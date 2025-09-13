/**
 * PIR Sensor Component
 * Handles PIR sensor integration and activity detection for the calendar application
 */
const PIRSensor = (function () {
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
  let reconnectTimeout = null;
  let reconnectAttempts = 0;
  const MAX_RECONNECT_ATTEMPTS = 10;

  const STATUS_CHECK_INTERVAL = 5000; // Check status every 5 seconds
  const ACTIVITY_ENDPOINT = "/pir/activity";
  const STATUS_ENDPOINT = "/pir/status";
  const START_ENDPOINT = "/pir/start";
  const STOP_ENDPOINT = "/pir/stop";
  const EVENTS_ENDPOINT = "/pir/events";
  const TEST_ENDPOINT = "/pir/trigger_test";

  // Private methods
  function createVisualIndicators() {
    // Only create indicators if PIR feedback is enabled
    if (!config || !config.show_pir_feedback) {
      return;
    }

    // Create motion detection indicator
    visualIndicator = document.createElement("div");
    visualIndicator.className = "pir-motion-indicator";
    visualIndicator.innerHTML = "👁️ Motion Detected";
    visualIndicator.style.display = "none";

    // Create status indicator
    statusIndicator = document.createElement("div");
    statusIndicator.className = "pir-status-indicator";
    statusIndicator.innerHTML =
      '<span class="pir-icon">📡</span> <span class="pir-status-text">PIR Sensor</span>';

    // Add to page
    document.body.appendChild(visualIndicator);
    document.body.appendChild(statusIndicator);

    // Update status based on configuration
    updateStatusIndicator();
  }

  function updateStatusIndicator() {
    if (!statusIndicator) return;

    const statusText = statusIndicator.querySelector(".pir-status-text");
    const statusIcon = statusIndicator.querySelector(".pir-icon");

    if (isMonitoring) {
      statusIndicator.classList.add("active");
      statusIndicator.classList.remove("inactive", "error");
      statusText.textContent = "PIR Active";
      statusIcon.textContent = "👁️";
    } else if (isInitialized) {
      statusIndicator.classList.add("inactive");
      statusIndicator.classList.remove("active", "error");
      statusText.textContent = "PIR Standby";
      statusIcon.textContent = "⏸️";
    } else {
      statusIndicator.classList.add("error");
      statusIndicator.classList.remove("active", "inactive");
      statusText.textContent = "PIR Error";
      statusIcon.textContent = "❌";
    }
  }

  function showMotionFeedback() {
    if (!visualIndicator || !config?.show_pir_feedback) return;

    // Clear any existing timeout
    if (motionFeedbackTimeout) {
      clearTimeout(motionFeedbackTimeout);
    }

    // Show motion indicator with animation
    visualIndicator.style.display = "block";
    visualIndicator.classList.add("motion-detected");

    // Create ripple effect
    const ripple = document.createElement("div");
    ripple.className = "motion-ripple";
    document.body.appendChild(ripple);

    // Position ripple at center of screen
    const rect = document.body.getBoundingClientRect();
    ripple.style.left = rect.width / 2 + "px";
    ripple.style.top = rect.height / 2 + "px";

    // Trigger ripple animation
    setTimeout(() => {
      ripple.classList.add("ripple-animate");
    }, 10);

    // Hide after delay
    motionFeedbackTimeout = setTimeout(() => {
      if (visualIndicator) {
        visualIndicator.style.display = "none";
        visualIndicator.classList.remove("motion-detected");
      }

      // Remove ripple
      if (ripple && document.body.contains(ripple)) {
        document.body.removeChild(ripple);
        ripple = null; // Clear reference
      }
      motionFeedbackTimeout = null; // Clear timeout reference
    }, 2000);
  }

  async function loadConfiguration() {
    try {
      // Try to load configuration from server
      const response = await fetch("/api/config");
      if (response.ok) {
        const fullConfig = await response.json();
        config = {
          show_pir_feedback: fullConfig.ui?.show_pir_feedback ?? true,
          animation_duration: fullConfig.ui?.animation_duration_ms ?? 300,
        };
      } else {
        // Use defaults
        config = {
          show_pir_feedback: true,
          animation_duration: 300,
        };
      }
    } catch (error) {
      // Could not load PIR configuration, using defaults
      config = {
        show_pir_feedback: true,
        animation_duration: 300,
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

      if (data.status === "initialized" && data.monitoring !== isMonitoring) {
        isMonitoring = data.monitoring;
        updateStatusIndicator();
        // PIR sensor monitoring status changed
      }

      return data;
    } catch (error) {
      console.error("Error checking PIR sensor status:", error);
      return null;
    }
  }

  // Helper function to make PIR control API calls
  async function pirControlRequest(endpoint, action, successState) {
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();

      if (data.success) {
        isMonitoring = successState;
        return true;
      } else {
        console.error(`Failed to ${action} PIR monitoring:`, data.message);
        return false;
      }
    } catch (error) {
      console.error(`Error ${action} PIR monitoring:`, error);
      return false;
    }
  }

  async function startPIRMonitoring() {
    return await pirControlRequest(START_ENDPOINT, "start", true);
  }

  async function stopPIRMonitoring() {
    return await pirControlRequest(STOP_ENDPOINT, "stop", false);
  }

  function startStatusChecking() {
    if (statusCheckInterval) return;

    statusCheckInterval = setInterval(async () => {
      const status = await checkPIRStatus();
      if (status && status.status === "initialized" && !status.monitoring && isInitialized) {
        // Try to restart monitoring if it stopped unexpectedly
        // PIR monitoring stopped unexpectedly, attempting to restart
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
    // Clean up any existing connection first
    stopEventStream();

    // Reset reconnect attempts when starting fresh
    reconnectAttempts = 0;

    eventSource = new EventSource(EVENTS_ENDPOINT);

    eventSource.onmessage = function (event) {
      try {
        const data = JSON.parse(event.data);

        if (data.type === "motion_detected") {
          // PIR motion detected via SSE

          // Show visual feedback
          showMotionFeedback();

          // Trigger the activity callback
          if (activityCallback && typeof activityCallback === "function") {
            activityCallback("motion");
          }
        } else if (data.type === "heartbeat") {
          // Heartbeat to keep connection alive
          reconnectAttempts = 0; // Reset on successful message
        }
      } catch (error) {
        console.error("Error parsing PIR SSE event:", error);
      }
    };

    eventSource.onerror = function (error) {
      console.error("PIR SSE connection error:", error);

      // Close the failed connection
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }

      // Try to reconnect with exponential backoff
      if (isInitialized && reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        reconnectAttempts++;
        const delay = Math.min(5000 * Math.pow(1.5, reconnectAttempts - 1), 60000); // Max 60 seconds

        // Clear any existing reconnect timeout
        if (reconnectTimeout) {
          clearTimeout(reconnectTimeout);
        }

        reconnectTimeout = setTimeout(() => {
          reconnectTimeout = null;
          if (isInitialized) {
            startEventStream();
          }
        }, delay);
      } else if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        console.error("PIR SSE: Max reconnection attempts reached. Stopping.");
      }
    };

    // PIR sensor event stream started
  }

  function stopEventStream() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
      // PIR sensor event stream stopped
    }

    // Clear reconnect timeout if exists
    if (reconnectTimeout) {
      clearTimeout(reconnectTimeout);
      reconnectTimeout = null;
    }

    // Reset reconnect attempts
    reconnectAttempts = 0;
  }

  // Public methods
  const publicAPI = {
    init: async function (callback = null) {
      if (isInitialized) {
        // PIR sensor already initialized
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
        // PIR sensor not available on backend
        updateStatusIndicator(); // Show error state
        return false;
      }

      // PIR sensor component initialized
      isInitialized = true;
      isMonitoring = status.monitoring;
      updateStatusIndicator();

      // Start monitoring if not already running
      if (!isMonitoring) {
        const started = await startPIRMonitoring();
        if (!started) {
          // Failed to start PIR monitoring during initialization
        }
        updateStatusIndicator();
      }

      // Start periodic status checking
      startStatusChecking();

      // Start event stream for real-time motion detection
      startEventStream();

      return true;
    },

    start: async function () {
      if (!isInitialized) {
        console.error("PIR sensor not initialized");
        return false;
      }

      return await startPIRMonitoring();
    },

    stop: async function () {
      if (!isInitialized) {
        console.error("PIR sensor not initialized");
        return false;
      }

      return await stopPIRMonitoring();
    },

    setActivityCallback: function (callback) {
      activityCallback = callback;
    },

    reportActivity: async function (activityType = "motion") {
      if (!isInitialized) {
        // PIR sensor not initialized, cannot report activity
        return false;
      }

      try {
        // Report activity to backend
        await fetch(ACTIVITY_ENDPOINT, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ type: activityType }),
        });

        // Trigger local activity callback
        if (activityCallback && typeof activityCallback === "function") {
          activityCallback(activityType);
        }

        // PIR activity reported
        return true;
      } catch (error) {
        console.error("Error reporting PIR activity:", error);
        return false;
      }
    },

    getStatus: function () {
      return {
        initialized: isInitialized,
        monitoring: isMonitoring,
      };
    },

    triggerTestMotion: async function () {
      if (!isInitialized) {
        // PIR sensor not initialized
        return false;
      }

      try {
        const response = await fetch(TEST_ENDPOINT, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
        });

        if (response.ok) {
          // Test motion triggered successfully
          return true;
        } else {
          console.error("Failed to trigger test motion");
          return false;
        }
      } catch (error) {
        console.error("Error triggering test motion:", error);
        return false;
      }
    },

    cleanup: function () {
      // Stop all ongoing operations
      stopStatusChecking();
      stopEventStream();

      // Clear any pending timeouts
      if (motionFeedbackTimeout) {
        clearTimeout(motionFeedbackTimeout);
        motionFeedbackTimeout = null;
      }

      // Stop monitoring if active
      if (isInitialized && isMonitoring) {
        stopPIRMonitoring();
      }

      // Remove visual elements
      if (visualIndicator && visualIndicator.parentNode) {
        visualIndicator.parentNode.removeChild(visualIndicator);
        visualIndicator = null;
      }

      if (statusIndicator && statusIndicator.parentNode) {
        statusIndicator.parentNode.removeChild(statusIndicator);
        statusIndicator = null;
      }

      // Remove any remaining ripple elements
      const ripples = document.querySelectorAll(".motion-ripple");
      ripples.forEach((ripple) => {
        if (ripple.parentNode) {
          ripple.parentNode.removeChild(ripple);
        }
      });

      // Reset state
      isInitialized = false;
      isMonitoring = false;
      activityCallback = null;
      config = null;
    },
  };

  return publicAPI;
})();

export default PIRSensor;
