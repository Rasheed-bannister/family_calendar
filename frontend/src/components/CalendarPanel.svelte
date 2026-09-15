<script lang="ts">
  import { calendar } from "$lib/stores/calendar.svelte";
  import { config } from "$lib/stores/config.svelte";
  import { formatTimeCompact } from "$lib/format";
  import type { CalendarEvent, DayCell } from "$lib/types";
  import EventModal from "$components/EventModal.svelte";
  import DatePickerModal from "$components/DatePickerModal.svelte";
  import QrModal from "$components/QrModal.svelte";

  const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MIN_SWIPE = 50;
  const MAX_DRIFT = 100;

  let showQr = $state(false);
  let showDatePicker = $state(false);
  let openEvent = $state<CalendarEvent | null>(null);

  const weeks = $derived(calendar.month?.weeks ?? []);
  const syncing = $derived(calendar.month?.sync_status === "running");

  function selectCell(cell: DayCell) {
    calendar.select(cell.date);
  }

  function cellKey(event: KeyboardEvent, cell: DayCell) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectCell(cell);
    }
  }

  // Swipe between months. touch-action: pan-y on the grid keeps horizontal
  // gestures delivered as pointer events while vertical scrolling of a
  // cell's event list still works.
  let swipe: { id: number; x: number; y: number } | null = null;

  function onPointerDown(event: PointerEvent) {
    swipe = { id: event.pointerId, x: event.clientX, y: event.clientY };
  }

  function onPointerUp(event: PointerEvent) {
    if (!swipe || swipe.id !== event.pointerId) return;
    const dx = event.clientX - swipe.x;
    const dy = event.clientY - swipe.y;
    swipe = null;
    if (Math.abs(dx) < MIN_SWIPE || Math.abs(dy) > MAX_DRIFT || Math.abs(dx) <= Math.abs(dy)) {
      return;
    }
    void (dx > 0 ? calendar.previous() : calendar.next());
  }

  function onPointerCancel() {
    swipe = null;
  }
</script>

<section class="glass calendar-panel">
  <header class="header">
    <h1 class="family">{config.value.app.family_name}</h1>
    <h2 class="month">
      {#if calendar.month}
        {calendar.month.month_name} {calendar.month.year}
      {/if}
      {#if syncing}
        <span class="sync" aria-live="polite">syncing…</span>
      {/if}
    </h2>
    <nav class="nav">
      <button class="btn" title="Get QR code for photo upload" onclick={() => (showQr = true)}>
        📱 Photos
      </button>
      <button class="btn" title="Jump to date" onclick={() => (showDatePicker = true)}>
        📅 Change Date
      </button>
      <button class="btn" title="Go to today" onclick={() => void calendar.goToToday()}>
        Today
      </button>
    </nav>
  </header>

  {#if calendar.error}
    <p class="error">Could not load calendar: {calendar.error}</p>
  {/if}

  <div
    class="grid"
    role="grid"
    aria-label="Month calendar"
    tabindex="-1"
    style:--weeks={weeks.length || 6}
    onpointerdown={onPointerDown}
    onpointerup={onPointerUp}
    onpointercancel={onPointerCancel}
  >
    <div class="weekdays" role="row">
      {#each WEEKDAYS as day (day)}
        <div class="weekday" role="columnheader">{day}</div>
      {/each}
    </div>
    {#each weeks as week, w (w)}
      <div class="week" role="row">
        {#each week as cell, d (cell?.date ?? `blank-${w}-${d}`)}
          {#if cell}
            <div
              class="cell"
              class:today={cell.is_today}
              class:selected={calendar.selectedDate === cell.date}
              role="button"
              tabindex="0"
              onclick={() => selectCell(cell)}
              onkeydown={(e) => cellKey(e, cell)}
            >
              <div class="day-number">{cell.day}</div>
              <div class="events">
                {#each cell.events as event (event.id)}
                  <button
                    class="event"
                    style:background-color={event.color}
                    style:border-left-color={event.color}
                    title={event.title}
                    onclick={(e) => {
                      e.stopPropagation();
                      openEvent = event;
                    }}
                  >
                    <span class="event-time">
                      {event.all_day ? "All Day" : formatTimeCompact(event.start)}
                    </span>
                    <span class="event-title">{event.title}</span>
                  </button>
                {/each}
              </div>
            </div>
          {:else}
            <div class="cell blank" aria-hidden="true"></div>
          {/if}
        {/each}
      </div>
    {/each}
  </div>
</section>

<QrModal open={showQr} onclose={() => (showQr = false)} />
<DatePickerModal open={showDatePicker} onclose={() => (showDatePicker = false)} />
<EventModal event={openEvent} onclose={() => (openEvent = null)} />

<style>
  .calendar-panel {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .header {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    align-items: center;
    gap: 15px;
    min-height: 40px;
    padding: 8px 15px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.2);
  }
  .family,
  .month {
    margin: 0;
    font-size: 1.4em;
    font-weight: 600;
    letter-spacing: 0.5px;
    text-shadow: 0 2px 4px rgba(0, 0, 0, 0.5);
  }
  .family {
    justify-self: start;
  }
  .month {
    justify-self: center;
    text-align: center;
  }
  .sync {
    margin-left: 0.6em;
    font-size: 0.6em;
    font-weight: 500;
    color: var(--text-muted);
  }
  .nav {
    display: flex;
    gap: 10px;
    justify-self: end;
  }
  .error {
    margin: 0;
    padding: 6px 15px;
    color: var(--danger);
    font-size: 0.9em;
  }

  .grid {
    flex: 1;
    min-height: 0;
    display: grid;
    grid-template-rows: auto repeat(var(--weeks), minmax(0, 1fr));
    gap: 3px;
    padding: 6px 8px 8px;
    touch-action: pan-y;
  }
  .weekdays,
  .week {
    display: grid;
    grid-template-columns: repeat(7, minmax(0, 1fr));
    gap: 3px;
    min-height: 0;
  }
  .weekday {
    padding: 8px 5px;
    text-align: center;
    font-size: 0.95em;
    font-weight: 600;
    background: rgba(0, 0, 0, 0.4);
    border-radius: 6px 6px 0 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.2);
  }

  .cell {
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
    border-radius: 6px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    background: rgba(255, 255, 255, 0.05);
    cursor: pointer;
  }
  .cell:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: -2px;
  }
  .cell.blank {
    background: rgba(0, 0, 0, 0.15);
    cursor: default;
  }
  .day-number {
    flex-shrink: 0;
    padding: 3px 6px;
    text-align: right;
    font-size: 0.9em;
    font-weight: 600;
    background: rgba(0, 0, 0, 0.3);
    border-bottom: 1px solid rgba(255, 255, 255, 0.2);
  }
  .events {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 2px;
    font-size: 0.7em;
  }

  .event {
    display: block;
    width: 100%;
    margin-bottom: 3px;
    padding: 2px 4px;
    border-radius: 4px;
    border: 1px solid rgba(0, 0, 0, 0.3);
    border-top-color: rgba(255, 255, 255, 0.2);
    border-left: 3px solid;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
    color: #fff;
    text-align: left;
    text-shadow: 1px 1px 3px rgba(0, 0, 0, 0.7);
    letter-spacing: 0.5px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .event-time {
    margin-right: 4px;
    font-weight: bold;
    letter-spacing: 1px;
  }

  .cell.today {
    background: #ffffcc;
    border: 2px solid #f0e68c;
  }
  .cell.today .day-number {
    color: #000;
    background: #f0e68c;
    text-shadow: none;
  }
  .cell.selected {
    background: #d0eaff;
    border: 2px solid #99ccff;
  }
  .cell.selected .day-number {
    color: #000;
    background: #b3d9ff;
    text-shadow: none;
  }
</style>
