// Mirror of the server's display state. The server decides the mode; this
// store only reflects it and forwards real user input as activity.

import { api } from "../api";
import { sse } from "../sse.svelte";
import type { DisplayMode, DisplaySnapshot } from "../types";

const ACTIVITY_THROTTLE_MS = 1_500;

class DisplayStore {
  mode = $state<DisplayMode>("active");
  brightness = $state(1);
  overlayBrightness = $state(1);
  isNight = $state(false);
  idleSeconds = $state(0);
  snapshot = $state<DisplaySnapshot | null>(null);
  loaded = $state(false);

  private lastSent = 0;
  private pending: string | null = null;
  private pendingTimer: ReturnType<typeof setTimeout> | null = null;

  readonly uiVisible = $derived(this.mode !== "slideshow");
  readonly dimmed = $derived(this.mode !== "active");

  apply(snapshot: DisplaySnapshot): void {
    this.snapshot = snapshot;
    this.mode = snapshot.mode;
    this.brightness = snapshot.brightness;
    this.overlayBrightness = snapshot.overlay_brightness;
    this.isNight = snapshot.is_night;
    this.idleSeconds = snapshot.idle_seconds;
    this.loaded = true;
  }

  async refresh(): Promise<void> {
    try {
      this.apply(await api.display());
    } catch (err) {
      console.warn("Could not fetch display state", err);
    }
  }

  /**
   * Report real input. Throttled: bursts of pointer events collapse to one
   * request, but the *first* event in a burst is sent immediately so a touch
   * on a sleeping screen wakes it without delay.
   */
  activity(source: string): void {
    const now = Date.now();
    if (now - this.lastSent >= ACTIVITY_THROTTLE_MS) {
      this.lastSent = now;
      void this.send(source);
      return;
    }
    this.pending = source;
    if (!this.pendingTimer) {
      this.pendingTimer = setTimeout(
        () => {
          this.pendingTimer = null;
          const pendingSource = this.pending;
          this.pending = null;
          if (pendingSource) {
            this.lastSent = Date.now();
            void this.send(pendingSource);
          }
        },
        ACTIVITY_THROTTLE_MS - (now - this.lastSent),
      );
    }
  }

  private async send(source: string): Promise<void> {
    try {
      this.apply(await api.activity(source));
    } catch (err) {
      console.warn("Could not report activity", err);
    }
  }

  async sleep(): Promise<void> {
    try {
      this.apply(await api.sleep());
    } catch (err) {
      console.warn("Could not force slideshow", err);
    }
  }

  start(): () => void {
    void this.refresh();
    const offChange = sse.on("display_changed", (event) => this.apply(event));
    const offPoll = sse.onFallbackPoll(() => void this.refresh());
    return () => {
      offChange();
      offPoll();
    };
  }
}

export const display = new DisplayStore();
