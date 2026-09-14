<script lang="ts">
  import Modal from "$components/Modal.svelte";
  import { api } from "$lib/api";
  import type { QrCodeResponse } from "$lib/types";

  let { open, onclose }: { open: boolean; onclose: () => void } = $props();

  let loading = $state(false);
  let error = $state<string | null>(null);
  let result = $state<QrCodeResponse | null>(null);

  const displayUrl = $derived(result?.url ? result.url.split("?")[0] + "…" : "");

  $effect(() => {
    if (!open) return;
    loading = true;
    error = null;
    result = null;
    api
      .qrCode()
      .then((data) => {
        if (data.success && data.qrcode) result = data;
        else error = "Failed to generate QR code";
      })
      .catch((err) => {
        console.error("Error generating QR code:", err);
        error = "Error generating QR code";
      })
      .finally(() => (loading = false));
  });
</script>

<Modal {open} title="📱 Upload Photos from Your Phone" {onclose} width="420px">
  <p class="lead">Scan this QR code with your phone's camera to upload photos</p>
  <div class="code">
    {#if loading}
      <span class="muted">Generating QR code…</span>
    {:else if error}
      <span class="error">{error}</span>
    {:else if result?.qrcode}
      <img src={result.qrcode} alt="Scan to open the phone upload page" />
    {/if}
  </div>
  {#if result}
    <div class="url">{displayUrl}</div>
    <div class="validity">⏱️ {result.message || "Valid for 60 minutes"}</div>
  {/if}
  <p class="hint">Make sure your phone is connected to the same Wi-Fi network</p>
</Modal>

<style>
  .lead {
    margin: 0 0 16px;
    color: var(--text-muted);
    text-align: center;
  }
  .code {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 220px;
    padding: 16px;
    border-radius: var(--radius-sm);
    background: #fff;
  }
  .code img {
    max-width: 100%;
    height: auto;
  }
  .muted {
    color: #666;
  }
  .error {
    color: #c62828;
  }
  .url {
    margin-top: 12px;
    font-size: 0.85em;
    color: var(--text-muted);
    text-align: center;
    word-break: break-all;
  }
  .validity {
    margin-top: 8px;
    text-align: center;
    font-weight: 600;
    color: var(--warn);
  }
  .hint {
    margin: 18px 0 0;
    font-size: 0.85em;
    color: var(--text-muted);
    text-align: center;
  }
</style>
