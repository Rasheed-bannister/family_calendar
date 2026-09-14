<script lang="ts">
  import { onMount } from "svelte";
  import { sse } from "$lib/sse.svelte";
  import { installActivityTracking } from "$lib/activity";
  import { setTimeZone } from "$lib/format";
  import { config } from "$lib/stores/config.svelte";
  import { display } from "$lib/stores/display.svelte";
  import { calendar } from "$lib/stores/calendar.svelte";
  import { chores } from "$lib/stores/chores.svelte";
  import { weather } from "$lib/stores/weather.svelte";

  import Slideshow from "$components/Slideshow.svelte";
  import DimOverlay from "$components/DimOverlay.svelte";
  import Toasts from "$components/Toasts.svelte";
  import MotionBadge from "$components/MotionBadge.svelte";
  import Weather from "$components/Weather.svelte";
  import CalendarPanel from "$components/CalendarPanel.svelte";
  import DayView from "$components/DayView.svelte";
  import Chores from "$components/Chores.svelte";
  import VirtualKeyboard from "$components/VirtualKeyboard.svelte";
  import SettingsPanel from "$components/SettingsPanel.svelte";

  let ready = $state(false);

  onMount(() => {
    const cleanups: Array<() => void> = [];
    (async () => {
      const cfg = await config.load();
      setTimeZone(cfg.app.timezone);
      document.body.classList.toggle("kiosk", cfg.ui.touch_optimized);

      sse.connect();
      cleanups.push(display.start(), calendar.start(), chores.start(), weather.start());
      cleanups.push(installActivityTracking());
      ready = true;
    })();

    return () => {
      for (const cleanup of cleanups) cleanup();
      sse.disconnect();
    };
  });
</script>

<Slideshow />

<div class="ui" class:hidden={!display.uiVisible} aria-hidden={!display.uiVisible}>
  {#if ready}
    <main class="layout">
      <section class="column column-main">
        <Weather />
        <CalendarPanel />
      </section>
      <section class="column column-side">
        <DayView />
        <Chores />
      </section>
    </main>
    <SettingsPanel />
    <VirtualKeyboard />
  {/if}
</div>

<MotionBadge />
<Toasts />
<DimOverlay />

<style>
  .ui {
    position: fixed;
    inset: 0;
    z-index: var(--z-ui);
    opacity: 1;
    transition: opacity var(--ui-fade) ease-in-out;
  }
  /* Hidden UI stays in the DOM (state survives, no re-init) but cannot be
     touched. The document-level activity listener still sees the touch and
     the server switches the mode back, which fades this in again. */
  .ui.hidden {
    opacity: 0;
    pointer-events: none;
  }

  .layout {
    display: flex;
    flex-direction: row;
    gap: var(--gap);
    height: 100vh;
    padding: var(--gap);
  }
  .column {
    display: flex;
    flex-direction: column;
    gap: var(--gap);
    min-width: 0;
    min-height: 0;
    height: 100%;
  }
  .column-main {
    flex: 4;
  }
  .column-side {
    flex: 1.15;
  }
</style>
