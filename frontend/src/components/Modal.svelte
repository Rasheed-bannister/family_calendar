<script lang="ts">
  // Generic modal shell: dark blurred backdrop, glass card, closes on
  // backdrop tap or Escape. Content is passed as a snippet.
  import type { Snippet } from "svelte";
  import { fade, scale } from "svelte/transition";

  let {
    open,
    title = "",
    onclose,
    width = "480px",
    keyboardRoom = false,
    children,
  }: {
    open: boolean;
    title?: string;
    onclose: () => void;
    width?: string;
    /** Shift the card up so the on-screen keyboard does not cover it. */
    keyboardRoom?: boolean;
    children: Snippet;
  } = $props();

  function onKey(event: KeyboardEvent) {
    if (event.key === "Escape") onclose();
  }
</script>

<svelte:window onkeydown={open ? onKey : undefined} />

{#if open}
  <div
    class="backdrop"
    class:keyboard-room={keyboardRoom}
    role="presentation"
    transition:fade={{ duration: 150 }}
    onpointerdown={(e) => {
      if (e.target === e.currentTarget) onclose();
    }}
  >
    <div
      class="card"
      role="dialog"
      aria-modal="true"
      aria-label={title || "Dialog"}
      tabindex="-1"
      style:max-width={width}
      transition:scale={{ start: 0.95, duration: 180 }}
    >
      <button class="close" aria-label="Close" onclick={onclose}>×</button>
      {#if title}
        <h2 class="title">{title}</h2>
      {/if}
      {@render children()}
    </div>
  </div>
{/if}

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    z-index: var(--z-modal);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 16px;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(5px);
    -webkit-backdrop-filter: blur(5px);
  }
  .backdrop.keyboard-room {
    align-items: flex-start;
    padding-bottom: 300px;
    overflow: auto;
  }
  .card {
    position: relative;
    width: 100%;
    max-height: calc(100vh - 32px);
    overflow: auto;
    padding: 24px 28px;
    background: var(--panel-bg);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius);
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
    color: var(--text);
  }
  .close {
    position: absolute;
    top: 8px;
    right: 14px;
    width: 40px;
    height: 40px;
    font-size: 28px;
    line-height: 1;
    color: var(--text-muted);
  }
  .close:hover {
    color: var(--text);
  }
  .title {
    margin: 0 0 14px;
    padding-right: 36px;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--glass-border);
    font-size: 1.3em;
    font-weight: 600;
  }
</style>
