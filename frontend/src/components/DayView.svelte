<script lang="ts">
  import { calendar } from "$lib/stores/calendar.svelte";
  import { eventTimeRange, formatLongDate, todayIso } from "$lib/format";

  const title = $derived(
    calendar.selectedDate && calendar.selectedDate !== todayIso()
      ? formatLongDate(calendar.selectedDate)
      : "Today's Events",
  );
</script>

<section class="glass day-view">
  <h2 class="panel-title">{title}</h2>
  {#if !calendar.selectedDate}
    <p class="empty">Select a day to see its events.</p>
  {:else if calendar.selectedEvents.length === 0}
    <p class="empty">No events for this day.</p>
  {:else}
    <ul>
      {#each calendar.selectedEvents as event (event.id)}
        <li style:border-left-color={event.color}>
          <strong>{event.title}</strong>
          <span class="meta">{event.calendar_name}</span>
          <span class="time">{eventTimeRange(event)}</span>
          {#if event.location}
            <small>Location: {event.location}</small>
          {/if}
          {#if event.description}
            <small class="notes">Notes: {event.description}</small>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .day-view {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    padding: 12px;
  }
  .panel-title {
    margin-bottom: 12px;
    padding-bottom: 8px;
    text-align: center;
    border-bottom: 1px solid var(--glass-border);
  }
  .empty {
    margin: 0;
    color: var(--text-muted);
  }
  ul {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    list-style: none;
    margin: 0;
    padding: 0;
  }
  li {
    display: flex;
    flex-direction: column;
    gap: 3px;
    margin-bottom: 10px;
    padding: 8px 12px;
    border-radius: var(--radius-sm);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-left: 5px solid #ccc;
    background: rgba(255, 255, 255, 0.05);
    font-size: 0.95em;
  }
  strong {
    font-size: 1.05em;
  }
  .meta {
    color: var(--text-muted);
    font-size: 0.85em;
  }
  .time {
    font-weight: 500;
  }
  small {
    opacity: 0.9;
    line-height: 1.3;
  }
  .notes {
    white-space: pre-wrap;
  }
</style>
