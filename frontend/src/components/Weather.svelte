<script lang="ts">
  // Weather strip: today's reading on the left, the next three days on the
  // right. Pure renderer of the weather store; the server refreshes the data.
  import { onMount } from "svelte";
  import { formatNow, formatTime, formatWeekday } from "$lib/format";
  import { weather } from "$lib/stores/weather.svelte";

  let clock = $state(formatNow());

  const current = $derived(weather.data?.current ?? null);
  const today = $derived(weather.data?.daily?.[0] ?? null);
  const forecast = $derived(weather.data?.daily?.slice(1, 4) ?? []);
  const stale = $derived(!!weather.data?.stale && !!weather.data?.cached_at);

  function degrees(value: number | null | undefined): string {
    return value === null || value === undefined ? "–" : `${Math.round(value)}°`;
  }

  function percent(value: number | null | undefined): string {
    return value === null || value === undefined ? "–" : `${Math.round(value)}%`;
  }

  onMount(() => {
    const timer = setInterval(() => {
      clock = formatNow();
    }, 30_000);
    return () => clearInterval(timer);
  });
</script>

<div class="weather glass" class:night={current && !current.is_day}>
  {#if weather.available && current && today}
    <div class="current">
      <div class="day-title">
        Today <span class="clock">{clock}</span>
        {#if stale}
          <span
            class="stale"
            title="Weather could not be refreshed; showing the last successful reading."
          >
            ⚠️ {formatTime(weather.data?.cached_at)}
          </span>
        {/if}
      </div>
      <div class="day-body">
        <div class="icon-column">
          <div class="sun">☀️ {formatTime(today.sunrise)}</div>
          <div class="icon big">{current.icon}</div>
          <div class="sun">🌙 {formatTime(today.sunset)}</div>
        </div>
        <div class="temps">
          <div class="high">{degrees(today.apparent_temperature_max)}</div>
          <div class="now">{degrees(current.apparent_temperature)}</div>
          <div class="low">{degrees(today.apparent_temperature_min)}</div>
        </div>
      </div>
    </div>

    <div class="forecast">
      {#each forecast as day (day.date)}
        <div class="forecast-day">
          <div class="day-title">{formatWeekday(day.date)}</div>
          <div class="day-body">
            <div class="icon-column">
              <div class="sun">☀️ {formatTime(day.sunrise)}</div>
              <div class="icon">{day.icon}</div>
              <div class="sun">🌙 {formatTime(day.sunset)}</div>
            </div>
            <div class="temps">
              <div class="high">{degrees(day.apparent_temperature_max)}</div>
              <div class="precip">🌧️ {percent(day.precipitation_probability_max)}</div>
              <div class="low">{degrees(day.apparent_temperature_min)}</div>
            </div>
          </div>
        </div>
      {/each}
    </div>
  {:else}
    <p class="unavailable">
      {weather.loaded ? "Weather data unavailable." : "Fetching weather…"}
    </p>
  {/if}
</div>

<style>
  .weather {
    display: flex;
    align-items: stretch;
    min-height: 90px;
    max-height: 120px;
    overflow: hidden;
    flex-shrink: 0;
  }

  .current {
    flex: 1 1 25%;
    display: flex;
    flex-direction: column;
    padding: 8px;
    border-right: 1px solid rgba(255, 255, 255, 0.2);
  }

  .forecast {
    flex: 3 1 75%;
    display: flex;
    justify-content: space-around;
    align-items: stretch;
    padding-left: 8px;
  }

  .forecast-day {
    flex: 1;
    display: flex;
    flex-direction: column;
    padding: 8px 6px;
    border-right: 1px solid rgba(255, 255, 255, 0.1);
  }
  .forecast-day:last-child {
    border-right: none;
  }

  .day-title {
    text-align: center;
    font-weight: 600;
    font-size: 0.95em;
    letter-spacing: 0.5px;
    padding-bottom: 4px;
    margin-bottom: 4px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.2);
    flex-shrink: 0;
  }
  .clock {
    font-family: var(--font-mono);
    font-weight: 500;
  }
  .stale {
    font-size: 0.8em;
    font-weight: 500;
    opacity: 0.75;
    white-space: nowrap;
    margin-left: 6px;
  }

  .day-body {
    display: flex;
    flex-direction: row;
    align-items: center;
    flex-grow: 1;
    width: 100%;
    min-height: 0;
  }

  .icon-column {
    flex: 1 1 50%;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    line-height: 1.1;
  }
  .icon {
    font-size: 2em;
  }
  .icon.big {
    font-size: 2.6em;
  }
  .sun {
    font-size: 0.7em;
    font-weight: 500;
    color: #f5f5f5;
    white-space: nowrap;
  }

  .temps {
    flex: 1 1 50%;
    display: flex;
    flex-direction: column;
    justify-content: space-around;
    align-items: center;
    height: 100%;
    padding: 0 3px;
  }
  .high {
    color: var(--hot);
    font-weight: 600;
  }
  .low {
    color: var(--cold);
    font-weight: 600;
  }
  .now {
    font-size: 2.2em;
    font-weight: 700;
    line-height: 1;
    text-shadow: 0 2px 8px rgba(0, 0, 0, 0.6);
  }
  .precip {
    font-size: 0.9em;
    font-weight: 500;
    white-space: nowrap;
  }

  .weather.night .current {
    background: linear-gradient(to bottom, rgba(28, 35, 63, 0.5), rgba(10, 14, 26, 0.5));
  }

  .unavailable {
    margin: auto;
    padding: 12px;
    color: var(--text-muted);
  }
</style>
