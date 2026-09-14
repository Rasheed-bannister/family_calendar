<script lang="ts">
  import Modal from "$components/Modal.svelte";
  import { eventTimeRange } from "$lib/format";
  import type { CalendarEvent } from "$lib/types";

  let { event, onclose }: { event: CalendarEvent | null; onclose: () => void } = $props();
</script>

<Modal open={event !== null} title={event?.title ?? ""} {onclose}>
  {#if event}
    <div class="details" style:--accent-color={event.color}>
      <p class="row"><span class="label">Calendar</span> {event.calendar_name}</p>
      <p class="row"><span class="label">Time</span> {eventTimeRange(event)}</p>
      {#if event.location}
        <p class="row"><span class="label">Location</span> {event.location}</p>
      {/if}
      {#if event.description}
        <p class="row description"><span class="label">Notes</span> {event.description}</p>
      {/if}
    </div>
  {/if}
</Modal>

<style>
  .details {
    border-left: 5px solid var(--accent-color, #ccc);
    padding-left: 14px;
  }
  .row {
    margin: 10px 0;
    line-height: 1.4;
    font-size: 1.05em;
  }
  .label {
    display: inline-block;
    min-width: 5.5em;
    color: var(--text-muted);
    font-size: 0.85em;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .description {
    white-space: pre-wrap;
  }
</style>
