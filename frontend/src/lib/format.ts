// Small date/time helpers. Every ISO string from the backend carries the
// display timezone offset, so `new Date(iso)` is the right instant and the
// formatter must be told the same zone to print wall-clock time.

let timeZone: string | undefined;

export function setTimeZone(name: string | undefined): void {
  timeZone = name && name !== "UTC" ? name : name;
  // Validate; fall back to the browser's zone if the name is unknown here.
  try {
    new Intl.DateTimeFormat("en-US", { timeZone }).format(new Date());
  } catch {
    timeZone = undefined;
  }
}

function fmt(options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat("en-US", { timeZone, ...options });
}

/** "3:05 PM" */
export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return fmt({ hour: "numeric", minute: "2-digit" }).format(date);
}

/** "3:05PM" (compact, for calendar cells) */
export function formatTimeCompact(iso: string | null | undefined): string {
  return formatTime(iso).replace(" ", "");
}

/** "Mon" */
export function formatWeekday(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return fmt({ weekday: "short" }).format(date);
}

/** "Monday, September 14" */
export function formatLongDate(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d, 12));
  return new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  }).format(date);
}

/** Current wall-clock time in the display zone, "3:05 PM". */
export function formatNow(): string {
  return fmt({ hour: "numeric", minute: "2-digit" }).format(new Date());
}

/** Today's date in the display zone as YYYY-MM-DD. */
export function todayIso(): string {
  const parts = fmt({ year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(
    new Date(),
  );
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

export function eventTimeRange(event: { all_day: boolean; start: string; end: string }): string {
  if (event.all_day) return "All Day";
  return `${formatTime(event.start)} - ${formatTime(event.end)}`;
}
