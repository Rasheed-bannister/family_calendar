// One EventSource for the whole page. Reconnects with backoff; while
// disconnected, `onFallbackPoll` fires periodically so stores can re-fetch.

import type { ServerEvent } from "./types";

type Listener = (event: ServerEvent) => void;

const RECONNECT_MIN_MS = 2_000;
const RECONNECT_MAX_MS = 60_000;
const FALLBACK_POLL_MS = 60_000;

class ServerEvents {
  private source: EventSource | null = null;
  private listeners = new Map<string, Set<Listener>>();
  private reconnectDelay = RECONNECT_MIN_MS;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private fallbackTimer: ReturnType<typeof setInterval> | null = null;
  private fallbackListeners = new Set<() => void>();
  private stopped = false;

  connected = $state(false);

  connect(): void {
    this.stopped = false;
    if (this.source) return;
    const source = new EventSource("/events");
    this.source = source;

    source.onopen = () => {
      this.connected = true;
      this.reconnectDelay = RECONNECT_MIN_MS;
      this.stopFallback();
      // Whatever happened while we were away, refresh everything once.
      this.emitFallback();
    };

    source.onmessage = (message) => {
      let event: ServerEvent;
      try {
        event = JSON.parse(message.data);
      } catch {
        return;
      }
      if (!event || event.type === "heartbeat") return;
      this.dispatch(event);
    };

    source.onerror = () => {
      this.disconnect(false);
      if (this.stopped) return;
      this.startFallback();
      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null;
        this.connect();
      }, this.reconnectDelay);
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, RECONNECT_MAX_MS);
    };
  }

  disconnect(stop = true): void {
    if (stop) this.stopped = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.source) {
      this.source.close();
      this.source = null;
    }
    this.connected = false;
    if (stop) this.stopFallback();
  }

  on<T extends ServerEvent["type"]>(
    type: T,
    listener: (event: Extract<ServerEvent, { type: T }>) => void,
  ): () => void {
    const set = this.listeners.get(type) ?? new Set();
    set.add(listener as Listener);
    this.listeners.set(type, set);
    return () => set.delete(listener as Listener);
  }

  /** Called on reconnect and, while disconnected, once a minute. */
  onFallbackPoll(listener: () => void): () => void {
    this.fallbackListeners.add(listener);
    return () => this.fallbackListeners.delete(listener);
  }

  private dispatch(event: ServerEvent): void {
    const set = this.listeners.get(event.type);
    if (!set) return;
    for (const listener of set) {
      try {
        listener(event);
      } catch (err) {
        console.error(`SSE listener for ${event.type} failed`, err);
      }
    }
  }

  private emitFallback(): void {
    for (const listener of this.fallbackListeners) {
      try {
        listener();
      } catch (err) {
        console.error("SSE fallback listener failed", err);
      }
    }
  }

  private startFallback(): void {
    if (this.fallbackTimer) return;
    this.fallbackTimer = setInterval(() => this.emitFallback(), FALLBACK_POLL_MS);
  }

  private stopFallback(): void {
    if (this.fallbackTimer) {
      clearInterval(this.fallbackTimer);
      this.fallbackTimer = null;
    }
  }
}

export const sse = new ServerEvents();
