<script lang="ts">
  import { fly } from "svelte/transition";
  import { toasts } from "$lib/stores/toasts.svelte";
</script>

<div class="toasts" aria-live="polite">
  {#each toasts.items as toast (toast.id)}
    <button
      class="toast {toast.kind}"
      transition:fly={{ y: 20, duration: 250 }}
      onclick={() => toasts.dismiss(toast.id)}
    >
      {toast.message}
    </button>
  {/each}
</div>

<style>
  .toasts {
    position: fixed;
    bottom: 16px;
    left: 50%;
    transform: translateX(-50%);
    z-index: var(--z-toast);
    display: flex;
    flex-direction: column;
    gap: 8px;
    align-items: center;
    pointer-events: none;
  }
  .toast {
    pointer-events: auto;
    padding: 10px 18px;
    border-radius: 999px;
    background: var(--panel-bg);
    border: 1px solid var(--glass-border);
    color: var(--text);
    box-shadow: var(--glass-shadow);
    font-size: 0.95em;
    text-align: center;
  }
  .toast.success {
    border-color: var(--success);
  }
  .toast.error {
    border-color: var(--danger);
  }
</style>
