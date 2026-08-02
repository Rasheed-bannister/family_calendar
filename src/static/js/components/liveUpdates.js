/**
 * Live Updates
 *
 * Owns the single EventSource connection to /events and fans incoming events
 * out to subscribers.
 *
 * Why this replaces polling
 * -------------------------
 * The app used to ask `/calendar/check-updates` every 10 seconds and, when the
 * answer was "yes", call window.location.reload(). On a wall-mounted display
 * that reload restarts the background slideshow, drops scroll position and
 * closes any open UI — a visible flash every time a chore is ticked off.
 * Now the server says what changed and we re-fetch only that fragment.
 *
 * Why a single connection
 * -----------------------
 * Flask's threaded server holds a thread per open SSE stream, and browsers cap
 * concurrent connections per host. pirSensor.js used to open its own stream to
 * /pir/events; it now subscribes here instead, so one display holds one
 * connection no matter how many components care about events.
 */

const STREAM_ENDPOINT = "/events";

// Reconnect backoff. EventSource reconnects on its own, but only for a clean
// server close — an error (server restart, network drop) needs handling.
const RECONNECT_BASE_MS = 2000;
const RECONNECT_MAX_MS = 60000;

// If the stream cannot be established at all, fall back to asking on a slow
// timer so the display still converges rather than freezing on stale data.
const FALLBACK_POLL_MS = 300000; // 5 minutes

const LiveUpdates = {
  eventSource: null,
  subscribers: new Map(),
  reconnectAttempts: 0,
  reconnectTimer: null,
  fallbackTimer: null,
  isConnected: false,
  initialized: false,

  /**
   * Subscribe to an event type. Returns an unsubscribe function.
   */
  on(eventType, handler) {
    if (!this.subscribers.has(eventType)) {
      this.subscribers.set(eventType, new Set());
    }
    this.subscribers.get(eventType).add(handler);
    return () => this.subscribers.get(eventType)?.delete(handler);
  },

  emit(eventType, payload) {
    const handlers = this.subscribers.get(eventType);
    if (!handlers) return;
    handlers.forEach((handler) => {
      try {
        handler(payload);
      } catch (err) {
        // One bad handler must not stop the others from seeing the event.
        console.error(`LiveUpdates: handler for "${eventType}" failed:`, err);
      }
    });
  },

  init() {
    if (this.initialized) return true;
    if (typeof EventSource === "undefined") {
      console.warn("LiveUpdates: EventSource unsupported; using fallback polling");
      this.startFallbackPolling();
      return false;
    }
    this.initialized = true;
    this.connect();
    return true;
  },

  connect() {
    this.disconnect();

    try {
      this.eventSource = new EventSource(STREAM_ENDPOINT);
    } catch (err) {
      console.error("LiveUpdates: could not open event stream:", err);
      this.scheduleReconnect();
      return;
    }

    this.eventSource.onopen = () => {
      this.isConnected = true;
      this.reconnectAttempts = 0;
      this.stopFallbackPolling();
      this.emit("connected", {});
    };

    this.eventSource.onmessage = (message) => {
      let data;
      try {
        data = JSON.parse(message.data);
      } catch (err) {
        console.error("LiveUpdates: malformed event payload:", err);
        return;
      }
      if (!data || !data.type) return;

      // A heartbeat only proves the connection is alive; nothing to dispatch.
      if (data.type === "heartbeat") {
        this.reconnectAttempts = 0;
        return;
      }
      this.emit(data.type, data);
    };

    this.eventSource.onerror = () => {
      this.isConnected = false;
      this.disconnect();
      this.scheduleReconnect();
    };
  },

  scheduleReconnect() {
    if (this.reconnectTimer) return;

    this.reconnectAttempts += 1;
    const delay = Math.min(
      RECONNECT_BASE_MS * Math.pow(1.5, this.reconnectAttempts - 1),
      RECONNECT_MAX_MS
    );

    // Once reconnects are visibly failing, start the slow poll so the display
    // still catches up rather than sitting on stale data indefinitely.
    if (this.reconnectAttempts >= 3) {
      this.startFallbackPolling();
    }

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  },

  disconnect() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
    this.isConnected = false;
  },

  /**
   * Degraded mode: ask the server what changed, on a slow timer.
   * Emits the same events as the stream, so subscribers need no special case.
   */
  startFallbackPolling() {
    if (this.fallbackTimer) return;
    this.fallbackTimer = setInterval(async () => {
      try {
        const now = new Date();
        const response = await fetch(
          `/calendar/check-updates/${now.getFullYear()}/${now.getMonth() + 1}`
        );
        if (!response.ok) return;
        const data = await response.json();
        if (data.events_changed) {
          this.emit("calendar_changed", {
            month: now.getMonth() + 1,
            year: now.getFullYear(),
          });
        }
        if (data.chores_changed) {
          this.emit("chores_changed", {});
        }
      } catch (err) {
        console.error("LiveUpdates: fallback poll failed:", err);
      }
    }, FALLBACK_POLL_MS);
  },

  stopFallbackPolling() {
    if (this.fallbackTimer) {
      clearInterval(this.fallbackTimer);
      this.fallbackTimer = null;
    }
  },

  destroy() {
    this.disconnect();
    this.stopFallbackPolling();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.subscribers.clear();
    this.initialized = false;
  },
};

/**
 * Replace a region of the page with freshly rendered server markup.
 *
 * The fragment endpoints render the same Jinja partials the full page uses, so
 * there is exactly one implementation of how a calendar cell or chore row
 * looks — no duplicated rendering logic in JavaScript to drift out of sync.
 */
export async function swapFragment(url, selector) {
  const target = document.querySelector(selector);
  if (!target) {
    console.warn(`LiveUpdates: no element matches "${selector}"; skipping swap`);
    return false;
  }

  let html;
  try {
    const response = await fetch(url, { headers: { "X-Requested-With": "fetch" } });
    if (!response.ok) {
      console.error(`LiveUpdates: fragment ${url} returned ${response.status}`);
      return false;
    }
    html = await response.text();
  } catch (err) {
    console.error(`LiveUpdates: could not fetch fragment ${url}:`, err);
    return false;
  }

  // Parse first, swap second: a failed parse must not blank the region.
  const parsed = new DOMParser().parseFromString(html, "text/html");
  const incoming = parsed.body.firstElementChild;
  if (!incoming) {
    console.error(`LiveUpdates: fragment ${url} contained no element`);
    return false;
  }

  target.replaceWith(incoming);
  return true;
}

export default LiveUpdates;
