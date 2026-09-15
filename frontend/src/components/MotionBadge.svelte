<script lang="ts">
  // Brief ripple when the PIR sensor reports motion, plus a small status
  // dot that turns red when the sensor was expected but is not working.
  // Both are opt-in via ui.show_pir_feedback; the error state always shows.
  import { onMount } from "svelte";
  import { api } from "$lib/api";
  import { sse } from "$lib/sse.svelte";
  import { config } from "$lib/stores/config.svelte";
  import type { PirStatus } from "$lib/types";

  let status = $state<PirStatus | null>(null);
  let ripple = $state(0);
  let rippleTimer: ReturnType<typeof setTimeout> | null = null;

  const broken = $derived(
    !!status && status.initialized && status.enabled && !status.simulation && !status.available,
  );
  const showFeedback = $derived(config.value.ui.show_pir_feedback);

  async function refresh(): Promise<void> {
    try {
      status = await api.pirStatus();
    } catch {
      status = null;
    }
  }

  onMount(() => {
    void refresh();
    const poll = setInterval(refresh, 60_000);
    const off = sse.on("motion_detected", () => {
      ripple += 1;
      if (rippleTimer) clearTimeout(rippleTimer);
      rippleTimer = setTimeout(() => (ripple = 0), 1200);
    });
    return () => {
      clearInterval(poll);
      off();
      if (rippleTimer) clearTimeout(rippleTimer);
    };
  });
</script>

{#if showFeedback && ripple > 0}
  {#key ripple}
    <div class="ripple" aria-hidden="true"></div>
  {/key}
{/if}

{#if broken}
  <div class="pir-dot error" title={status?.error ?? "PIR sensor not working"}>
    <span class="dot"></span> motion sensor
  </div>
{:else if showFeedback && status?.available}
  <div class="pir-dot ok" title="PIR sensor active on GPIO {status.pin}">
    <span class="dot"></span>
  </div>
{/if}

<style>
  .ripple {
    position: fixed;
    right: 24px;
    bottom: 24px;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    border: 2px solid rgba(129, 199, 132, 0.9);
    z-index: var(--z-toast);
    pointer-events: none;
    animation: ripple 1.1s ease-out forwards;
  }
  @keyframes ripple {
    from {
      transform: scale(0.4);
      opacity: 1;
    }
    to {
      transform: scale(4);
      opacity: 0;
    }
  }
  .pir-dot {
    position: fixed;
    right: 14px;
    bottom: 14px;
    z-index: var(--z-toast);
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 8px;
    border-radius: 999px;
    font-size: 0.75em;
    color: var(--text-muted);
    background: rgba(0, 0, 0, 0.35);
    pointer-events: none;
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--success);
    box-shadow: 0 0 6px var(--success);
  }
  .pir-dot.error {
    color: #fff;
    background: rgba(229, 115, 115, 0.35);
  }
  .pir-dot.error .dot {
    background: var(--danger);
    box-shadow: 0 0 6px var(--danger);
  }
</style>
