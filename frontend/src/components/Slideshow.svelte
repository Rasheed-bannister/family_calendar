<script lang="ts">
  // Always-on photo background. Two slides exist during a crossfade; the
  // outgoing one is held (not faded) underneath the incoming one so the
  // screen never dips to black mid-transition.
  //
  // Each photo gets a slow Ken Burns move: scale and translate on the
  // image only (compositor-friendly), direction randomised per photo.
  // Photos whose aspect ratio is far from the screen's are shown with
  // `contain` over a blurred copy of themselves instead of being cropped
  // to their middle.
  import { onMount } from "svelte";
  import { fade } from "svelte/transition";
  import { api } from "$lib/api";
  import { sse } from "$lib/sse.svelte";
  import { config } from "$lib/stores/config.svelte";
  import type { SlidePhoto } from "$lib/types";

  interface Slide extends SlidePhoto {
    seq: number;
    fit: "cover" | "contain";
    kb: { scale: number; x: number; y: number; originX: number; originY: number };
    durationMs: number;
  }

  let current = $state<Slide | null>(null);
  let empty = $state(false);
  let seq = 0;

  let timer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;
  let preloaded: { photo: SlidePhoto; img: HTMLImageElement } | null = null;
  let viewportRatio = $state(window.innerWidth / Math.max(1, window.innerHeight));

  const intervalMs = $derived(Math.max(5, config.value.slideshow.interval_seconds) * 1000);
  const fadeMs = $derived(Math.max(0.2, config.value.slideshow.transition_seconds) * 1000);
  const kenBurns = $derived(config.value.slideshow.ken_burns);

  // Hold the outgoing slide in place for the length of the fade, then drop it.
  function hold(_node: Element, { duration }: { duration: number }) {
    return { duration };
  }

  function pickFit(photo: SlidePhoto): "cover" | "contain" {
    if (!photo.width || !photo.height) return "cover";
    const ratio = photo.width / photo.height;
    const mismatch = Math.max(ratio / viewportRatio, viewportRatio / ratio);
    // A 4:3 photo on a 16:9 screen (1.33 vs 1.78 → 1.33x) still covers well;
    // a 3:4 portrait (2.37x) would lose most of its frame.
    return mismatch > 1.45 ? "contain" : "cover";
  }

  function makeKenBurns() {
    const r = (min: number, max: number) => min + Math.random() * (max - min);
    return {
      scale: r(1.08, 1.16),
      x: r(-2.5, 2.5),
      y: r(-2.5, 2.5),
      originX: r(30, 70),
      originY: r(30, 70),
    };
  }

  async function fetchAndDecode(): Promise<{ photo: SlidePhoto; img: HTMLImageElement } | null> {
    const next = await api.nextPhoto();
    if (!next.url) {
      empty = !!next.empty;
      return null;
    }
    empty = false;
    const photo = next as SlidePhoto;
    const img = new Image();
    img.decoding = "async";
    img.src = photo.url;
    try {
      await img.decode();
    } catch {
      // A broken file: skip it rather than showing a blank layer.
      return null;
    }
    return { photo, img };
  }

  function show(photo: SlidePhoto): void {
    seq += 1;
    current = {
      ...photo,
      seq,
      fit: pickFit(photo),
      kb: makeKenBurns(),
      durationMs: intervalMs + fadeMs + 1500,
    };
  }

  function schedule(delay: number): void {
    if (timer) clearTimeout(timer);
    timer = setTimeout(advance, delay);
  }

  async function advance(): Promise<void> {
    timer = null;
    if (disposed) return;
    if (document.hidden) {
      schedule(5000);
      return;
    }
    try {
      const ready = preloaded ?? (await fetchAndDecode());
      preloaded = null;
      if (ready) show(ready.photo);
    } catch (err) {
      console.warn("Slideshow: could not load next photo", err);
    }
    // Preload the following photo a little before it is due.
    const lead = Math.min(8000, intervalMs / 3);
    setTimeout(
      async () => {
        if (disposed) return;
        try {
          preloaded = await fetchAndDecode();
        } catch {
          preloaded = null;
        }
      },
      Math.max(1000, intervalMs - lead),
    );
    schedule(current ? intervalMs : empty ? 30_000 : 5000);
  }

  onMount(() => {
    const onResize = () => {
      viewportRatio = window.innerWidth / Math.max(1, window.innerHeight);
    };
    window.addEventListener("resize", onResize);
    const offPhotos = sse.on("photos_changed", () => {
      // New photos: if nothing is showing yet, try again right away.
      if (!current) schedule(500);
    });
    const onVisible = () => {
      if (!document.hidden && !timer) schedule(0);
    };
    document.addEventListener("visibilitychange", onVisible);

    void advance();

    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
      window.removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", onVisible);
      offPhotos();
    };
  });
</script>

<div class="slideshow" aria-hidden="true">
  {#if current}
    {#key current.seq}
      <div
        class="slide"
        class:kb={kenBurns}
        style:z-index={current.seq}
        style:--kb-scale={current.kb.scale}
        style:--kb-x="{current.kb.x}%"
        style:--kb-y="{current.kb.y}%"
        style:--kb-origin="{current.kb.originX}% {current.kb.originY}%"
        style:--kb-duration="{current.durationMs}ms"
        in:fade={{ duration: fadeMs }}
        out:hold={{ duration: fadeMs + 100 }}
      >
        {#if current.fit === "contain"}
          <img class="backdrop" src={current.url} alt="" draggable="false" />
        {/if}
        <img class="photo {current.fit}" src={current.url} alt="" draggable="false" />
      </div>
    {/key}
  {:else if empty}
    <div class="placeholder">
      <p>No photos yet</p>
      <p class="hint">Use the 📱 Photos button to upload some from your phone.</p>
    </div>
  {/if}
</div>

<style>
  .slideshow {
    position: fixed;
    inset: 0;
    z-index: 0;
    background: #000;
    overflow: hidden;
  }
  .slide {
    position: absolute;
    inset: 0;
    overflow: hidden;
    background: #000;
  }
  .photo,
  .backdrop {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    display: block;
    transform-origin: var(--kb-origin, 50% 50%);
    will-change: transform;
    backface-visibility: hidden;
  }
  .photo.cover {
    object-fit: cover;
  }
  .photo.contain {
    object-fit: contain;
  }
  .backdrop {
    object-fit: cover;
    filter: blur(28px) brightness(0.55) saturate(1.2);
    transform: scale(1.15);
  }
  .slide.kb .photo {
    animation: ken-burns var(--kb-duration, 34s) linear forwards;
  }
  @keyframes ken-burns {
    from {
      transform: scale(1) translate(0, 0);
    }
    to {
      transform: scale(var(--kb-scale, 1.12)) translate(var(--kb-x, 0), var(--kb-y, 0));
    }
  }
  .placeholder {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background: radial-gradient(ellipse at center, #1e2a44 0%, #0b0f1a 70%);
    color: var(--text-muted);
    text-align: center;
    padding: 2rem;
  }
  .placeholder p {
    margin: 0.3em 0;
    font-size: 1.4em;
  }
  .placeholder .hint {
    font-size: 1em;
  }
</style>
