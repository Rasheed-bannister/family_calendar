// Month data plus which day is selected. Re-fetches on `calendar_changed`
// for the displayed month; the server only publishes that when the data
// actually differs, so a re-fetch never feeds back into another sync.

import { api } from "../api";
import { sse } from "../sse.svelte";
import { todayIso } from "../format";
import type { CalendarEvent, DayCell, MonthPayload } from "../types";

// After this long without interaction, the day panel snaps back to today
// and the grid returns to the current month. Purely a view convenience: it
// never counts as, or interferes with, display activity.
const RETURN_TO_TODAY_MS = 5 * 60 * 1000;

class CalendarStore {
  month = $state<MonthPayload | null>(null);
  selectedDate = $state<string | null>(null);
  loading = $state(false);
  error = $state<string | null>(null);

  private returnTimer: ReturnType<typeof setTimeout> | null = null;
  private clockTimer: ReturnType<typeof setInterval> | null = null;
  private lastToday = todayIso();

  readonly year = $derived(this.month?.year ?? 0);
  readonly monthNumber = $derived(this.month?.month ?? 0);

  readonly selectedCell = $derived.by((): DayCell | null => {
    if (!this.month || !this.selectedDate) return null;
    for (const week of this.month.weeks) {
      for (const cell of week) {
        if (cell && cell.date === this.selectedDate) return cell;
      }
    }
    return null;
  });

  readonly selectedEvents = $derived<CalendarEvent[]>(this.selectedCell?.events ?? []);

  readonly isCurrentMonth = $derived.by(() => {
    if (!this.month) return true;
    const [y, m] = todayIso().split("-").map(Number);
    return this.month.year === y && this.month.month === m;
  });

  async load(year: number, month: number, opts: { keepSelection?: boolean } = {}): Promise<void> {
    this.loading = true;
    this.error = null;
    try {
      const payload = await api.month(year, month);
      this.month = payload;
      const today = payload.today;
      const todayVisible = payload.weeks.some((w) => w.some((c) => c?.date === today));
      if (opts.keepSelection && this.selectedDate && this.selectedCell) {
        // keep
      } else if (todayVisible) {
        this.selectedDate = today;
      } else {
        this.selectedDate = null;
      }
    } catch (err) {
      this.error = err instanceof Error ? err.message : String(err);
      console.error("Could not load month", err);
    } finally {
      this.loading = false;
    }
  }

  /** Re-fetch the displayed month without changing the selection. */
  async reload(): Promise<void> {
    if (!this.month) return;
    await this.load(this.month.year, this.month.month, { keepSelection: true });
  }

  select(date: string): void {
    this.selectedDate = date;
    this.touch();
  }

  async goToToday(): Promise<void> {
    const [y, m] = todayIso().split("-").map(Number);
    await this.load(y, m);
    this.selectedDate = todayIso();
  }

  async goToMonth(year: number, month: number): Promise<void> {
    await this.load(year, month);
    this.touch();
  }

  async next(): Promise<void> {
    if (!this.month) return;
    await this.goToMonth(this.month.next.year, this.month.next.month);
  }

  async previous(): Promise<void> {
    if (!this.month) return;
    await this.goToMonth(this.month.prev.year, this.month.prev.month);
  }

  /** Any calendar interaction: restarts the return-to-today timer. */
  touch(): void {
    if (this.returnTimer) clearTimeout(this.returnTimer);
    this.returnTimer = setTimeout(() => {
      this.returnTimer = null;
      void this.goToToday();
    }, RETURN_TO_TODAY_MS);
  }

  start(): () => void {
    void this.goToToday();

    const offChanged = sse.on("calendar_changed", (event) => {
      if (this.month && event.year === this.month.year && event.month === this.month.month) {
        void this.reload();
      }
    });
    const offPoll = sse.onFallbackPoll(() => void this.reload());

    // Roll over at midnight: the "today" highlight and the day panel must
    // move without anyone touching the screen.
    this.clockTimer = setInterval(() => {
      const today = todayIso();
      if (today !== this.lastToday) {
        this.lastToday = today;
        void this.goToToday();
      }
    }, 30_000);

    return () => {
      offChanged();
      offPoll();
      if (this.clockTimer) clearInterval(this.clockTimer);
      if (this.returnTimer) clearTimeout(this.returnTimer);
    };
  }
}

export const calendar = new CalendarStore();
