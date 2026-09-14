import type {
  AppConfig,
  Chore,
  ChoreStatus,
  DayPayload,
  DisplaySnapshot,
  MonthPayload,
  PirStatus,
  QrCodeResponse,
  SlideshowNext,
  SlideshowSettings,
  UpgradeStatus,
  VersionInfo,
  WeatherPayload,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    cache: "no-store",
    ...init,
    headers: { Accept: "application/json", ...(init.headers || {}) },
  });
  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!response.ok) {
    const record = body && typeof body === "object" ? (body as Record<string, unknown>) : null;
    const message =
      (record && typeof record.error === "string" && record.error) ||
      (record && typeof record.message === "string" && record.message) ||
      `${response.status} ${response.statusText}`;
    throw new ApiError(response.status, message, body);
  }
  return body as T;
}

function post<T>(path: string, data?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
}

export const api = {
  config: () => request<AppConfig>("/api/config"),

  display: () => request<DisplaySnapshot>("/api/display"),
  activity: (source: string) => post<DisplaySnapshot>("/api/display/activity", { source }),
  sleep: () => post<DisplaySnapshot>("/api/display/sleep"),

  month: (year: number, month: number, sync = true) =>
    request<MonthPayload>(`/api/calendar/${year}/${month}${sync ? "" : "?sync=0"}`),
  day: (date: string) => request<DayPayload>(`/api/calendar/day/${date}`),

  chores: () => request<{ chores: Chore[] }>("/api/chores").then((r) => r.chores),
  addChore: (person: string, text: string) =>
    post<{ success: boolean; message: string; id: string }>("/chores/add", {
      title: person,
      notes: text,
    }),
  setChoreStatus: (id: string, status: ChoreStatus) =>
    post<{ success: boolean }>(`/chores/update_status/${encodeURIComponent(id)}`, { status }),

  weather: () => request<WeatherPayload>("/api/weather"),

  nextPhoto: () => request<SlideshowNext>("/api/slideshow/next"),
  slideshowSettings: () => request<SlideshowSettings>("/api/slideshow/settings"),

  pirStatus: () => request<PirStatus>("/pir/status"),
  pirDiagnostics: () => request<Record<string, any>>("/pir/diagnostics"),
  pirTestMotion: () => post<{ success: boolean }>("/pir/trigger_test"),

  version: (checkUpdate = false) =>
    request<VersionInfo>(`/api/version${checkUpdate ? "?check_update=true" : ""}`),
  upgrade: (tag: string) => post<{ success: boolean; message: string }>("/api/upgrade", { tag }),
  upgradeStatus: () => request<UpgradeStatus>("/api/upgrade/status"),

  qrCode: () => request<QrCodeResponse>("/upload/qrcode"),
};
