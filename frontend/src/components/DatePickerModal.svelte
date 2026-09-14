<script lang="ts">
  import Modal from "$components/Modal.svelte";
  import { calendar } from "$lib/stores/calendar.svelte";

  let { open, onclose }: { open: boolean; onclose: () => void } = $props();

  const MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
  ];

  const currentYear = new Date().getFullYear();
  const years = Array.from({ length: 11 }, (_, i) => currentYear - 5 + i);

  let month = $state(new Date().getMonth() + 1);
  let year = $state(currentYear);

  // Start from the month currently on screen each time the picker opens.
  $effect(() => {
    if (open && calendar.month) {
      month = calendar.month.month;
      year = calendar.month.year;
    }
  });

  function go() {
    onclose();
    void calendar.goToMonth(year, month);
  }
</script>

<Modal {open} title="Jump to Date" {onclose} width="380px">
  <div class="controls">
    <select class="field" aria-label="Month" bind:value={month}>
      {#each MONTHS as name, i (name)}
        <option value={i + 1}>{name}</option>
      {/each}
    </select>
    <select class="field" aria-label="Year" bind:value={year}>
      {#each years as y (y)}
        <option value={y}>{y}</option>
      {/each}
    </select>
  </div>
  <div class="buttons">
    <button class="btn" onclick={onclose}>Cancel</button>
    <button class="btn btn-primary" onclick={go}>Go</button>
  </div>
</Modal>

<style>
  .controls {
    display: flex;
    gap: 12px;
    margin-bottom: 20px;
  }
  .buttons {
    display: flex;
    gap: 12px;
    justify-content: flex-end;
  }
  .buttons .btn {
    min-width: 90px;
  }
</style>
