// Shapes of the JSON the Flask backend serves. Keep in sync with the routes
// in src/*/routes.py; the backend is the source of truth for every field.

export type DisplayMode = "active" | "dimmed" | "slideshow";

export interface DisplayThresholds {
  dim_after_seconds: number;
  hide_ui_after_seconds: number;
  brightness: number;
}

export interface DisplaySnapshot {
  mode: DisplayMode;
  brightness: number;
  /** 1.0 when a hardware backlight is doing the dimming; else the CSS overlay level. */
  overlay_brightness: number;
  is_night: boolean;
  idle_seconds: number;
  last_activity_source: string | null;
  last_activity_at: string | null;
  thresholds: DisplayThresholds;
  backlight: { backend: string; available: boolean; [k: string]: unknown };
}

export interface AppConfig {
  app: { family_name: string; debug: boolean; environment: string; timezone: string };
  display: {
    night_start_hour: number;
    night_end_hour: number;
    day: DisplayThresholds;
    night: DisplayThresholds;
  };
  slideshow: { interval_seconds: number; transition_seconds: number; ken_burns: boolean };
  google: { sync_interval_minutes: number };
  weather: { cache_duration: number };
  ui: { show_pir_feedback: boolean; touch_optimized: boolean; animation_duration_ms: number };
}

export interface CalendarEvent {
  id: string;
  title: string;
  calendar_name: string;
  color: string;
  all_day: boolean;
  /** ISO 8601 with offset, in the display timezone. */
  start: string;
  end: string;
  location: string;
  description: string;
}

export interface DayCell {
  date: string; // YYYY-MM-DD
  day: number;
  is_today: boolean;
  events: CalendarEvent[];
}

export interface MonthPayload {
  year: number;
  month: number;
  month_name: string;
  today: string;
  weeks: (DayCell | null)[][];
  prev: { year: number; month: number };
  next: { year: number; month: number };
  sync_status: string | null;
}

export interface DayPayload {
  date: string;
  events: CalendarEvent[];
}

export type ChoreStatus = "needsAction" | "completed" | "invisible";

export interface Chore {
  id: string;
  person: string;
  text: string;
  status: ChoreStatus;
  due: string | null;
}

export interface WeatherDay {
  date: string;
  weather_code: number | null;
  icon: string;
  apparent_temperature_max: number | null;
  apparent_temperature_min: number | null;
  sunrise: string | null;
  sunset: string | null;
  precipitation_probability_max: number | null;
}

export interface WeatherPayload {
  available: boolean;
  current?: {
    time: string | null;
    apparent_temperature: number | null;
    is_day: boolean;
    weather_code: number | null;
    icon: string;
  };
  daily?: WeatherDay[];
  stale?: boolean;
  cached_at?: string | null;
  age_seconds?: number | null;
  sync_status?: string | null;
}

export interface SlidePhoto {
  url: string;
  filename: string;
  width: number | null;
  height: number | null;
  orientation: "landscape" | "portrait" | "square" | "unknown";
}

export interface SlideshowNext extends Partial<Omit<SlidePhoto, "url">> {
  url: string | null;
  empty?: boolean;
}

export interface SlideshowSettings {
  interval_seconds: number;
  transition_seconds: number;
  ken_burns: boolean;
  photo_count: number;
}

export interface PirStatus {
  initialized: boolean;
  enabled: boolean;
  simulation: boolean;
  available: boolean;
  pin?: number;
  pin_factory?: string | null;
  error?: string | null;
  gpiozero_installed?: boolean;
  motion_count?: number;
  seconds_since_motion?: number | null;
}

export interface VersionInfo {
  current_version: string;
  update_available?: boolean;
  latest_version?: string | null;
  release_url?: string | null;
}

export interface UpgradeStatus {
  state: "idle" | "running" | "restarting" | "done" | "error";
  message: string;
}

export interface QrCodeResponse {
  success: boolean;
  qrcode?: string; // data: URL
  url?: string;
  message?: string;
}

// Server-sent events. Every frame carries `type` and `timestamp`.
export type ServerEvent =
  | ({ type: "display_changed" } & DisplaySnapshot)
  | { type: "motion_detected" }
  | { type: "calendar_changed"; month: number; year: number }
  | { type: "chores_changed" }
  | { type: "photos_changed"; count?: number }
  | { type: "weather_changed" }
  | { type: "heartbeat" };
