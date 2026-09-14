import { api } from "../api";
import type { AppConfig } from "../types";

const DEFAULTS: AppConfig = {
  app: { family_name: "Family", debug: false, environment: "production", timezone: "UTC" },
  display: {
    night_start_hour: 21,
    night_end_hour: 6,
    day: { dim_after_seconds: 3600, hide_ui_after_seconds: 3605, brightness: 0.6 },
    night: { dim_after_seconds: 5, hide_ui_after_seconds: 10, brightness: 0.2 },
  },
  slideshow: { interval_seconds: 30, transition_seconds: 2, ken_burns: true },
  google: { sync_interval_minutes: 5 },
  weather: { cache_duration: 600 },
  ui: { show_pir_feedback: true, touch_optimized: true, animation_duration_ms: 300 },
};

class ConfigStore {
  value = $state<AppConfig>(DEFAULTS);
  loaded = $state(false);

  async load(): Promise<AppConfig> {
    try {
      const fetched = await api.config();
      this.value = {
        ...DEFAULTS,
        ...fetched,
        app: { ...DEFAULTS.app, ...fetched.app },
        display: { ...DEFAULTS.display, ...fetched.display },
        slideshow: { ...DEFAULTS.slideshow, ...fetched.slideshow },
        google: { ...DEFAULTS.google, ...fetched.google },
        weather: { ...DEFAULTS.weather, ...fetched.weather },
        ui: { ...DEFAULTS.ui, ...fetched.ui },
      };
    } catch (err) {
      console.warn("Could not load config; using defaults", err);
    }
    this.loaded = true;
    return this.value;
  }
}

export const config = new ConfigStore();
