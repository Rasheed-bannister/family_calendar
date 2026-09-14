<script lang="ts">
  // On-screen keyboard for the touchscreen. Edits whichever field the
  // `keyboard` store points at; hides when the field is released or the
  // user taps somewhere that is neither the keyboard nor the field.
  import { onMount } from "svelte";
  import { keyboard } from "$lib/stores/keyboard.svelte";
  import { config } from "$lib/stores/config.svelte";

  type Layout = "standard" | "symbols";

  const LAYOUTS: Record<Layout, string[][]> = {
    standard: [
      ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "Backspace"],
      ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
      ["a", "s", "d", "f", "g", "h", "j", "k", "l"],
      ["Shift", "z", "x", "c", "v", "b", "n", "m", ",", ".", "?"],
      ["123", "Space", "Enter"],
    ],
    symbols: [
      ["!", "@", "#", "$", "%", "^", "&", "*", "(", ")", "Backspace"],
      ["-", "_", "=", "+", "[", "]", "{", "}", "\\", "|"],
      [";", ":", "'", '"', "<", ">", "/", "?"],
      ["~", "`", ",", ".", "!", "?", "Enter"],
      ["ABC", "Space"],
    ],
  };

  const LONG_PRESS_MS = 500;
  const REPEAT_MS = 60;

  let layout = $state<Layout>("standard");
  let shift = $state(false);
  let capsLock = $state(false);
  let lastShiftTap = 0;
  let root = $state<HTMLElement | null>(null);

  let repeatDelay: ReturnType<typeof setTimeout> | null = null;
  let repeatTimer: ReturnType<typeof setInterval> | null = null;

  const rows = $derived(LAYOUTS[layout]);
  const upper = $derived(shift || capsLock);

  function label(key: string): string {
    switch (key) {
      case "Backspace":
        return "⌫";
      case "Enter":
        return "↵";
      case "Shift":
        return capsLock ? "⇪" : "⇧";
      case "Space":
        return "";
      default:
        return key.length === 1 && upper ? key.toUpperCase() : key;
    }
  }

  function keyClass(key: string): string {
    switch (key) {
      case "Backspace":
        return "key key-backspace key-wide";
      case "Enter":
        return "key key-enter key-wide";
      case "Shift":
        return `key key-shift key-wide${upper ? " active" : ""}`;
      case "Space":
        return "key key-space";
      case "123":
      case "ABC":
        return "key key-layout key-wide";
      default:
        return "key";
    }
  }

  function haptic(): void {
    if (config.value.ui.touch_optimized) navigator.vibrate?.(10);
  }

  function notifyInput(el: HTMLInputElement | HTMLTextAreaElement): void {
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function insert(text: string): void {
    const el = keyboard.target;
    if (!el) return;
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? el.value.length;
    const max = el.maxLength > 0 ? el.maxLength : Infinity;
    if (el.value.length - (end - start) + text.length > max) return;
    el.setRangeText(text, start, end, "end");
    notifyInput(el);
  }

  function backspace(): void {
    const el = keyboard.target;
    if (!el) return;
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? el.value.length;
    if (start === end) {
      if (start === 0) return;
      el.setRangeText("", start - 1, end, "end");
    } else {
      el.setRangeText("", start, end, "end");
    }
    notifyInput(el);
  }

  function stopRepeat(): void {
    if (repeatDelay) clearTimeout(repeatDelay);
    if (repeatTimer) clearInterval(repeatTimer);
    repeatDelay = null;
    repeatTimer = null;
  }

  function press(key: string): void {
    haptic();
    switch (key) {
      case "Backspace":
        backspace();
        return;
      case "Enter":
        keyboard.onEnter?.();
        return;
      case "Shift": {
        const now = Date.now();
        if (now - lastShiftTap < 350) {
          capsLock = !capsLock;
          shift = false;
        } else if (capsLock) {
          capsLock = false;
          shift = false;
        } else {
          shift = !shift;
        }
        lastShiftTap = now;
        return;
      }
      case "Space":
        insert(" ");
        return;
      case "123":
        layout = "symbols";
        return;
      case "ABC":
        layout = "standard";
        return;
      default:
        insert(upper ? key.toUpperCase() : key);
        if (shift) shift = false;
    }
  }

  function onKeyDown(event: PointerEvent, key: string): void {
    // Keep focus (and the caret) in the field being edited.
    event.preventDefault();
    keyboard.target?.focus({ preventScroll: true });
    if (key === "Backspace") {
      backspace();
      haptic();
      stopRepeat();
      repeatDelay = setTimeout(() => {
        repeatTimer = setInterval(backspace, REPEAT_MS);
      }, LONG_PRESS_MS);
      return;
    }
    press(key);
  }

  function onKeyUp(): void {
    stopRepeat();
  }

  onMount(() => {
    // Tap outside both the keyboard and the field it edits: release it.
    const onDocumentPointerDown = (event: PointerEvent) => {
      if (!keyboard.open) return;
      const node = event.target as Node | null;
      if (!node) return;
      if (root?.contains(node)) return;
      if (keyboard.target?.contains(node)) return;
      keyboard.hide();
    };
    document.addEventListener("pointerdown", onDocumentPointerDown, { capture: true });
    return () => {
      document.removeEventListener("pointerdown", onDocumentPointerDown, { capture: true });
      stopRepeat();
    };
  });

  $effect(() => {
    if (!keyboard.open) {
      stopRepeat();
      shift = false;
      capsLock = false;
      layout = "standard";
    }
  });
</script>

<div
  class="keyboard"
  class:visible={keyboard.open}
  bind:this={root}
  role="group"
  aria-label="On-screen keyboard"
  aria-hidden={!keyboard.open}
>
  {#each rows as row, i (layout + i)}
    <div class="row">
      {#each row as key (key)}
        <button
          type="button"
          class={keyClass(key)}
          data-key={key}
          tabindex="-1"
          aria-label={key}
          onpointerdown={(e) => onKeyDown(e, key)}
          onpointerup={onKeyUp}
          onpointercancel={onKeyUp}
          onpointerleave={onKeyUp}
          oncontextmenu={(e) => e.preventDefault()}
        >
          {label(key)}
        </button>
      {/each}
    </div>
  {/each}
</div>

<style>
  .keyboard {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: calc(var(--z-modal) + 1);
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 12px;
    background: linear-gradient(135deg, rgba(42, 42, 46, 0.97), rgba(52, 52, 56, 0.97));
    border-top: 2px solid rgba(255, 255, 255, 0.1);
    box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.4);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    transform: translateY(100%);
    transition: transform 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94);
    pointer-events: none;
    touch-action: none;
  }
  .keyboard.visible {
    transform: translateY(0);
    pointer-events: auto;
  }
  .row {
    display: flex;
    justify-content: center;
    gap: 6px;
  }
  .key {
    flex: 1;
    min-width: 44px;
    max-width: 96px;
    height: 52px;
    padding: 0 6px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 8px;
    border: 1px solid rgba(255, 255, 255, 0.2);
    background: linear-gradient(145deg, rgba(255, 255, 255, 0.95), rgba(240, 240, 245, 0.95));
    box-shadow:
      0 3px 6px rgba(0, 0, 0, 0.15),
      inset 0 1px 0 rgba(255, 255, 255, 0.5);
    color: #333;
    font-size: 18px;
    font-weight: 600;
    user-select: none;
    touch-action: manipulation;
    transition:
      transform 0.08s ease,
      box-shadow 0.08s ease;
  }
  .key:active {
    transform: translateY(1px) scale(0.98);
    background: linear-gradient(145deg, rgba(220, 220, 230, 0.95), rgba(210, 210, 220, 0.95));
    box-shadow:
      0 1px 3px rgba(0, 0, 0, 0.2),
      inset 0 2px 4px rgba(0, 0, 0, 0.1);
  }
  .key-wide {
    flex: 2;
    min-width: 80px;
    max-width: 160px;
  }
  .key-space {
    flex: 6;
    min-width: 140px;
    max-width: 560px;
  }
  .key-backspace {
    background: linear-gradient(145deg, rgba(255, 100, 100, 0.9), rgba(240, 80, 80, 0.9));
    color: #fff;
    font-size: 22px;
  }
  .key-enter {
    background: linear-gradient(145deg, rgba(100, 180, 100, 0.9), rgba(80, 160, 80, 0.9));
    color: #fff;
    font-size: 22px;
    font-weight: 700;
  }
  .key-shift {
    background: linear-gradient(145deg, rgba(100, 150, 255, 0.9), rgba(80, 130, 240, 0.9));
    color: #fff;
    font-size: 20px;
  }
  .key-shift.active {
    background: linear-gradient(145deg, rgba(140, 185, 255, 0.98), rgba(110, 160, 250, 0.98));
    box-shadow:
      0 3px 6px rgba(0, 0, 0, 0.2),
      inset 0 0 10px rgba(255, 255, 255, 0.35);
  }
  .key-layout {
    background: linear-gradient(145deg, rgba(150, 150, 150, 0.9), rgba(130, 130, 130, 0.9));
    color: #fff;
    font-size: 14px;
    font-weight: 700;
  }
  @media (max-width: 768px) {
    .keyboard {
      padding: 8px;
      gap: 6px;
    }
    .key {
      height: 46px;
      min-width: 32px;
      font-size: 16px;
    }
    .key-wide {
      min-width: 56px;
    }
    .key-space {
      min-width: 100px;
    }
  }
</style>
