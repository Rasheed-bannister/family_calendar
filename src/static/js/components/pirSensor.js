/**
 * PIR Sensor Component
 * Handles PIR sensor integration and activity detection for the calendar application
 *
 * Motion arrives over the shared event stream owned by LiveUpdates rather than
 * a connection of this component's own; see startEventStream below.
 */
import LiveUpdates from "./liveUpdates.js";

const PIRSensor = (function () {
  // Private variables
  let isInitialized = false;
  let isMonitoring = false;
  let statusCheckInterval = null;
  let activityCallback = null;
  let unsubscribeMotion = null;
  let visualIndicator = null;
  let statusIndicator = null;
  let motionFeedbackTimeout = null;
  let config = null;

  const STATUS_CHECK_INTERVAL = 5000; // Check status every 5 seconds
  const STATUS_ENDPOINT = "/pir/status";
  const START_ENDPOINT = "/pir/start";
  const STOP_ENDPOINT = "/pir/stop";
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

  let activeRipple = null; // Track current ripple element to prevent leaks

  function showMotionFeedback() {
    if (!visualIndicator || !config?.show_pir_feedback) return;

    // Clear any existing timeout and clean up previous ripple
    if (motionFeedbackTimeout) {
      clearTimeout(motionFeedbackTimeout);
      motionFeedbackTimeout = null;
    }

    // Remove previous ripple before creating a new one
    if (activeRipple && activeRipple.parentNode) {
      activeRipple.parentNode.removeChild(activeRipple);
      activeRipple = null;
    }

    // Show motion indicator with animation
    visualIndicator.style.display = "block";
    visualIndicator.classList.add("motion-detected");

    // Create ripple effect
    activeRipple = document.createElement("div");
    activeRipple.className = "motion-ripple";
    document.body.appendChild(activeRipple);

    // Position ripple at center of screen
    const rect = document.body.getBoundingClientRect();
    activeRipple.style.left = rect.width / 2 + "px";
    activeRipple.style.top = rect.height / 2 + "px";

    // Trigger ripple animation
    setTimeout(() => {
      if (activeRipple) {
        activeRipple.classList.add("ripple-animate");
      }
    }, 10);

    // Hide after delay
    motionFeedbackTimeout = setTimeout(() => {
      if (visualIndicator) {
        visualIndicator.style.display = "none";
        visualIndicator.classList.remove("motion-detected");
      }

      // Remove ripple
      if (activeRipple && activeRipple.parentNode) {
        activeRipple.parentNode.removeChild(activeRipple);
        activeRipple = null;
      }
      motionFeedbackTimeout = null;
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
    // Motion now arrives on the shared /events stream owned by
    // liveUpdates.js, rather than this component opening its own connection
    // to /pir/events. Flask's threaded server holds a thread per open SSE
    // stream, so two streams per display cost a thread and a browser
    // connection slot for no benefit. LiveUpdates owns reconnection.
    stopEventStream();

    unsubscribeMotion = LiveUpdates.on("motion_detected", () => {
      showMotionFeedback();
      if (activityCallback && typeof activityCallback === "function") {
        activityCallback("motion");
      }
    });

    // Ensure the shared stream is running; init() is idempotent, so it is
    // safe whether or not app.js got there first.
    LiveUpdates.init();
  }

  function stopEventStream() {
    if (unsubscribeMotion) {
      unsubscribeMotion();
      unsubscribeMotion = null;
    }
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

      // Remove tracked ripple element
      if (activeRipple && activeRipple.parentNode) {
        activeRipple.parentNode.removeChild(activeRipple);
        activeRipple = null;
      }

      // Remove any remaining ripple elements (safety net)
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
