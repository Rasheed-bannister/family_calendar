<script lang="ts">
  // Gear button (bottom-left) and its panel: version/update, display state,
  // motion sensor status + diagnostics, live-update connection.
  import { onMount } from "svelte";
  import { fly } from "svelte/transition";
  import { api } from "$lib/api";
  import { sse } from "$lib/sse.svelte";
  import { config } from "$lib/stores/config.svelte";
  import { display } from "$lib/stores/display.svelte";
  import { toasts } from "$lib/stores/toasts.svelte";
  import type { PirStatus, UpgradeStatus, VersionInfo } from "$lib/types";

  const UPDATE_CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000;
  const UPGRADE_POLL_MS = 2_000;
  const RESTART_POLL_MS = 3_000;
  const RESTART_TIMEOUT_MS = 2 * 60 * 1000;

  let open = $state(false);
  let root = $state<HTMLDivElement | null>(null);

  let version = $state<VersionInfo | null>(null);
  let checking = $state(false);
  let upgrading = $state(false);
  let upgradeMessage = $state("");

  let pir = $state<PirStatus | null>(null);
  let diagRunning = $state(false);
  let diag = $state<Record<string, any> | null>(null);
  let diagError = $state<string | null>(null);

  const updateAvailable = $derived(!!version?.update_available && !!version.latest_version);
  const latestTag = $derived(version?.latest_version ? `v${version.latest_version}` : "");

  type PirView = { level: "ok" | "warn" | "off" | "error"; text: string };
  const pirView = $derived.by((): PirView => {
    if (!pir) return { level: "off", text: "Unknown" };
    if (!pir.initialized)
      return { level: "error", text: `Not working: ${pir.error ?? "not initialized"}` };
    if (!pir.enabled) return { level: "off", text: "Disabled" };
    if (pir.simulation) return { level: "warn", text: "Simulation mode" };
    if (pir.available) {
      const factory = pir.pin_factory ? ` (${pir.pin_factory})` : "";
      return { level: "ok", text: `Active on GPIO ${pir.pin}${factory}` };
    }
    return { level: "error", text: `Not working: ${pir.error ?? "unknown error"}` };
  });

  async function loadVersion(checkUpdate: boolean): Promise<void> {
    checking = checkUpdate;
    try {
      const info = await api.version(checkUpdate);
      // A plain version read must not erase a previously found update.
      version = checkUpdate ? info : { ...(version ?? {}), ...info };
    } catch (err) {
      if (checkUpdate) toasts.show("Could not check for updates", "error");
      console.warn("Version check failed", err);
    } finally {
      checking = false;
    }
  }

  async function loadPir(): Promise<void> {
    try {
      pir = await api.pirStatus();
    } catch {
      pir = null;
    }
  }

  function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function waitForRestart(): Promise<void> {
    upgradeMessage = "Restarting… the page will reload shortly.";
    const deadline = Date.now() + RESTART_TIMEOUT_MS;
    while (Date.now() < deadline) {
      await sleep(RESTART_POLL_MS);
      try {
        const info = await api.version();
        if (info.current_version && info.current_version !== version?.current_version) {
          location.reload();
          return;
        }
      } catch {
        // Server still down; keep waiting.
      }
    }
    upgradeMessage = "Server did not restart in time. Please reload manually.";
    upgrading = false;
  }

  async function applyUpdate(): Promise<void> {
    if (!latestTag || upgrading) return;
    upgrading = true;
    upgradeMessage = "Starting upgrade…";
    try {
      const result = await api.upgrade(latestTag);
      upgradeMessage = result.message;
      if (!result.success) {
        upgrading = false;
        return;
      }
    } catch (err) {
      upgradeMessage = err instanceof Error ? err.message : "Failed to start upgrade.";
      upgrading = false;
      return;
    }

    // Poll until the server reports it is restarting, done, or failed.
    for (;;) {
      await sleep(UPGRADE_POLL_MS);
      let status: UpgradeStatus;
      try {
        status = await api.upgradeStatus();
      } catch {
        // Likely mid-restart; treat as restarting.
        await waitForRestart();
        return;
      }
      upgradeMessage = status.message;
      if (status.state === "restarting") {
        await waitForRestart();
        return;
      }
      if (status.state === "done") {
        upgrading = false;
        return;
      }
      if (status.state === "error") {
        upgrading = false;
        toasts.show("Upgrade failed", "error");
        return;
      }
    }
  }

  async function runDiagnostics(): Promise<void> {
    diagRunning = true;
    diagError = null;
    try {
      diag = await api.pirDiagnostics();
    } catch (err) {
      diag = null;
      diagError = err instanceof Error ? err.message : "Failed to run diagnostics";
    } finally {
      diagRunning = false;
    }
  }

  async function testMotion(): Promise<void> {
    try {
      await api.pirTestMotion();
      toasts.show("Test motion sent", "success", 1500);
    } catch (err) {
      toasts.show(err instanceof Error ? err.message : "Test motion failed", "error");
    }
  }

  async function startSlideshow(): Promise<void> {
    open = false;
    await display.sleep();
  }

  function toggle(): void {
    open = !open;
    if (open) {
      void loadVersion(false);
      void loadPir();
    }
  }

  onMount(() => {
    void loadVersion(true);
    const checkTimer = setInterval(() => void loadVersion(true), UPDATE_CHECK_INTERVAL_MS);
    const onDocPointer = (event: PointerEvent) => {
      if (!open || !root) return;
      if (!root.contains(event.target as Node)) open = false;
    };
    document.addEventListener("pointerdown", onDocPointer, true);
    return () => {
      clearInterval(checkTimer);
      document.removeEventListener("pointerdown", onDocPointer, true);
    };
  });

  type Row = { label: string; value: string; ok?: boolean };
  const diagRows = $derived.by((): Row[] => {
    if (!diag) return [];
    const p = diag.platform ?? {};
    const libs = diag.libraries ?? {};
    const gpio = diag.gpio_devices ?? {};
    const cfg = diag.config ?? {};
    const sensor = diag.sensor ?? {};
    const probe = diag.gpio_probe ?? {};
    const power = diag.power ?? {};
    const chips: any[] = gpio.chips ?? [];
    const accessibleChips = chips.filter((c) => c.accessible).map((c) => c.path);
    return [
      { label: "Platform", value: p.model ?? p.machine ?? "?", ok: !!p.is_arm },
      { label: "Python", value: p.python ?? "?" },
      { label: "gpiozero", value: libs.gpiozero ?? "missing", ok: !!libs.gpiozero },
      { label: "lgpio", value: libs.lgpio ?? "missing", ok: !!libs.lgpio },
      { label: "Pin factory", value: libs.pin_factory ?? "–", ok: !!libs.pin_factory },
      {
        label: "GPIO chips",
        value: chips.length ? `${accessibleChips.length}/${chips.length} writable` : "none found",
        ok: accessibleChips.length > 0,
      },
      { label: "gpio group", value: gpio.username ?? "?", ok: !!gpio.gpio_group },
      { label: "Config pin", value: `GPIO ${cfg.pin ?? "?"}` },
      {
        label: "Sensor",
        value: sensor.available
          ? "open"
          : sensor.simulation
            ? "simulation"
            : (sensor.error ?? "not open"),
        ok: !!sensor.available || !!sensor.simulation,
      },
      {
        label: "Probe",
        value: probe.error ? probe.error : `value ${probe.value ?? "?"}`,
        ok: !!probe.success,
      },
      {
        label: "Power",
        value: power.available ? (power.flags?.length ? power.flags.join(", ") : "ok") : "n/a",
        ok: power.available ? !power.flags?.length : undefined,
      },
    ];
  });
</script>

<div class="settings" bind:this={root}>
  <button class="gear" aria-label="Settings" onclick={toggle}>
    ⚙
    {#if updateAvailable}
      <span class="badge" aria-hidden="true"></span>
    {/if}
  </button>

  {#if open}
    <div
      class="panel"
      transition:fly={{ y: 10, duration: 160 }}
      role="dialog"
      aria-label="Settings"
    >
      <div class="header">
        <span>Settings</span>
        <button class="close" aria-label="Close" onclick={() => (open = false)}>×</button>
      </div>

      <div class="body">
        <div class="section-label">Version</div>
        <div class="row">
          <span class="label">Installed</span>
          <span class="value mono">{version?.current_version ?? "…"}</span>
        </div>
        <div
          class="status"
          class:has-update={updateAvailable}
          class:up-to-date={version && !updateAvailable}
        >
          {#if checking}
            Checking…
          {:else if !version}
            Not checked yet
          {:else if updateAvailable}
            {latestTag} available
          {:else}
            Up to date
          {/if}
        </div>
        <div class="actions">
          <button
            class="btn small"
            disabled={checking || upgrading}
            onclick={() => loadVersion(true)}
          >
            Check for updates
          </button>
          {#if updateAvailable}
            <button class="btn small btn-primary" disabled={upgrading} onclick={applyUpdate}>
              {upgrading ? "Upgrading…" : `Update to ${latestTag}`}
            </button>
          {/if}
        </div>
        {#if upgradeMessage}
          <div class="progress">{upgradeMessage}</div>
        {/if}

        <div class="divider"></div>
        <div class="section-label">Display</div>
        <div class="row">
          <span class="label">Mode</span>
          <span class="value">{display.mode}</span>
        </div>
        <div class="row">
          <span class="label">Idle</span>
          <span class="value mono">{Math.round(display.idleSeconds)}s</span>
        </div>
        <div class="row">
          <span class="label">Night</span>
          <span class="value">{display.isNight ? "yes" : "no"}</span>
        </div>
        <div class="row">
          <span class="label">Backlight</span>
          <span class="value">{display.snapshot?.backlight.backend ?? "…"}</span>
        </div>
        <div class="actions">
          <button class="btn small" onclick={startSlideshow}>Start slideshow now</button>
        </div>

        <div class="divider"></div>
        <div class="section-label">Motion sensor</div>
        <div class="pir">
          <span class="dot {pirView.level}"></span>
          <span>{pirView.text}</span>
        </div>
        <div class="actions">
          <button class="btn small" disabled={diagRunning} onclick={runDiagnostics}>
            {diagRunning ? "Running…" : "Run diagnostics"}
          </button>
          {#if config.value.app.debug}
            <button class="btn small" onclick={testMotion}>Test motion</button>
          {/if}
        </div>
        {#if diagError}
          <div class="diag-error">{diagError}</div>
        {:else if diag}
          <div class="diag">
            {#each diagRows as row (row.label)}
              <div class="diag-row">
                <span
                  class="diag-dot"
                  class:ok={row.ok === true}
                  class:fail={row.ok === false}
                  class:na={row.ok === undefined}
                ></span>
                <span class="diag-label">{row.label}</span>
                <span class="diag-value" title={row.value}>{row.value}</span>
              </div>
            {/each}
            {#if diag.issues?.length}
              <div class="issues">
                {#each diag.issues as issue}
                  <div class="issue">• {issue}</div>
                {/each}
              </div>
            {:else}
              <div class="all-clear">All checks passed</div>
            {/if}
          </div>
        {/if}

        <div class="divider"></div>
        <div class="row">
          <span class="label">Live updates</span>
          <span class="value" class:ok-text={sse.connected} class:fail-text={!sse.connected}>
            {sse.connected ? "connected" : "disconnected"}
          </span>
        </div>
      </div>
    </div>
  {/if}
</div>

<style>
  .settings {
    position: fixed;
    bottom: 10px;
    left: 10px;
    z-index: var(--z-modal);
  }
  .gear {
    position: relative;
    width: 36px;
    height: 36px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.1);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
    color: rgba(255, 255, 255, 0.45);
    font-size: 18px;
    line-height: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    transition:
      color 0.2s,
      background 0.2s;
  }
  .gear:hover,
  .gear:active {
    background: rgba(255, 255, 255, 0.2);
    color: rgba(255, 255, 255, 0.85);
  }
  .badge {
    position: absolute;
    top: -2px;
    right: -2px;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: #ff4444;
    border: 2px solid rgba(0, 0, 0, 0.4);
  }

  .panel {
    position: absolute;
    bottom: 44px;
    left: 0;
    width: 280px;
    max-height: calc(100vh - 80px);
    overflow-y: auto;
    background: var(--panel-bg);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius);
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
    color: #e0e0e0;
    font-size: 13px;
    text-shadow: none;
  }
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 14px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    font-weight: 600;
    font-size: 14px;
    color: #fff;
    position: sticky;
    top: 0;
    background: var(--panel-bg);
  }
  .close {
    width: 44px;
    height: 44px;
    margin: -12px -14px -12px 0;
    color: var(--text-muted);
    font-size: 20px;
    line-height: 1;
  }
  .close:hover {
    color: #fff;
  }
  .body {
    padding: 12px 14px;
  }
  .row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6px;
    gap: 8px;
  }
  .label {
    color: var(--text-muted);
  }
  .value {
    color: #fff;
  }
  .mono {
    font-family: var(--font-mono);
  }
  .ok-text {
    color: var(--success);
  }
  .fail-text {
    color: var(--danger);
  }
  .status {
    font-size: 12px;
    color: var(--text-muted);
    margin-bottom: 8px;
  }
  .status.has-update {
    color: var(--accent);
    font-weight: 600;
  }
  .status.up-to-date {
    color: var(--success);
  }
  .actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-top: 4px;
  }
  .btn.small {
    min-height: 44px;
    padding: 6px 12px;
    font-size: 12px;
    text-shadow: none;
    backdrop-filter: none;
  }
  .progress {
    margin-top: 10px;
    padding: 8px 10px;
    background: rgba(255, 255, 255, 0.05);
    border-radius: 6px;
    font-size: 11px;
    color: rgba(255, 255, 255, 0.7);
    line-height: 1.4;
  }
  .divider {
    border-top: 1px solid rgba(255, 255, 255, 0.1);
    margin: 12px 0;
  }
  .section-label {
    font-weight: 600;
    font-size: 12px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 8px;
  }
  .pir {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 10px;
    font-size: 12px;
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
    background: rgba(255, 255, 255, 0.3);
  }
  .dot.ok {
    background: var(--success);
    box-shadow: 0 0 6px rgba(129, 199, 132, 0.5);
  }
  .dot.warn {
    background: var(--warn);
    box-shadow: 0 0 6px rgba(255, 183, 77, 0.5);
  }
  .dot.error {
    background: var(--danger);
    box-shadow: 0 0 6px rgba(229, 115, 115, 0.5);
  }
  .diag {
    margin-top: 10px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .diag-row {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 3px 6px;
    border-radius: 4px;
    font-size: 11px;
    background: rgba(255, 255, 255, 0.03);
  }
  .diag-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
    background: rgba(255, 255, 255, 0.25);
  }
  .diag-dot.ok {
    background: var(--success);
  }
  .diag-dot.fail {
    background: var(--danger);
  }
  .diag-label {
    color: var(--text-muted);
    min-width: 76px;
    flex-shrink: 0;
  }
  .diag-value {
    color: #e0e0e0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .diag-error,
  .issues {
    margin-top: 8px;
    padding: 6px 8px;
    background: rgba(229, 115, 115, 0.1);
    border: 1px solid rgba(229, 115, 115, 0.2);
    border-radius: 6px;
    font-size: 11px;
    color: #ef9a9a;
  }
  .issue {
    padding: 2px 0;
  }
  .all-clear {
    margin-top: 8px;
    padding: 6px 8px;
    background: rgba(129, 199, 132, 0.1);
    border: 1px solid rgba(129, 199, 132, 0.2);
    border-radius: 6px;
    font-size: 11px;
    color: var(--success);
  }
</style>
