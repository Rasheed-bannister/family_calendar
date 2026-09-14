import { api } from "../api";
import { sse } from "../sse.svelte";
import type { WeatherPayload } from "../types";

// The server refreshes on its own schedule and pushes `weather_changed`;
// this poll only covers the case where the SSE stream is down.
const REFRESH_MS = 10 * 60 * 1000;

class WeatherStore {
  data = $state<WeatherPayload | null>(null);
  loaded = $state(false);
  private timer: ReturnType<typeof setInterval> | null = null;

  readonly available = $derived(!!this.data?.available && !!this.data.current && !!this.data.daily);

  async load(): Promise<void> {
    try {
      this.data = await api.weather();
    } catch (err) {
      console.error("Could not load weather", err);
    } finally {
      this.loaded = true;
    }
  }

  start(): () => void {
    void this.load();
    const offChanged = sse.on("weather_changed", () => void this.load());
    const offPoll = sse.onFallbackPoll(() => void this.load());
    this.timer = setInterval(() => void this.load(), REFRESH_MS);
    return () => {
      offChanged();
      offPoll();
      if (this.timer) clearInterval(this.timer);
    };
  }
}

export const weather = new WeatherStore();
