<script lang="ts">
  // CSS dimming, used only when the server reports no hardware backlight
  // (`overlay_brightness` is 1.0 whenever the real backlight is doing the
  // work). Sits above everything, so toasts and modals cannot punch
  // through a dimmed screen at full brightness.
  import { display } from "$lib/stores/display.svelte";

  const alpha = $derived(Math.min(0.95, Math.max(0, 1 - display.overlayBrightness)));
</script>

<div class="dim" style:opacity={alpha} aria-hidden="true"></div>

<style>
  .dim {
    position: fixed;
    inset: 0;
    z-index: var(--z-dim);
    background: #000;
    pointer-events: none;
    transition: opacity 1.2s ease;
  }
</style>
