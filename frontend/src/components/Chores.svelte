<script lang="ts">
  // Chores grouped by person. Tap toggles done; a completed chore can be
  // swiped left to reveal a delete button that hides it from the list.
  import { onMount } from "svelte";
  import { chores } from "$lib/stores/chores.svelte";
  import type { Chore } from "$lib/types";
  import AddChoreModal from "$components/AddChoreModal.svelte";

  const SWIPE_THRESHOLD = 60; // px; matches the delete button width
  const TAP_SLOP = 8; // px of movement still counted as a tap

  let addOpen = $state(false);
  let swipedId = $state<string | null>(null);
  let dragId = $state<string | null>(null);
  let dragOffset = $state(0);
  let root = $state<HTMLElement | null>(null);

  let pointerId: number | null = null;
  let startX = 0;
  let startY = 0;
  let moved = false;

  function offsetFor(chore: Chore): number {
    if (dragId === chore.id) return dragOffset;
    if (swipedId === chore.id) return -SWIPE_THRESHOLD;
    return 0;
  }

  function onPointerDown(event: PointerEvent, chore: Chore): void {
    if (event.button !== 0 && event.pointerType === "mouse") return;
    // Tapping a different row closes any open delete button.
    if (swipedId && swipedId !== chore.id) swipedId = null;
    pointerId = event.pointerId;
    startX = event.clientX;
    startY = event.clientY;
    moved = false;
    if (chore.status === "completed") {
      dragId = chore.id;
      dragOffset = swipedId === chore.id ? -SWIPE_THRESHOLD : 0;
      (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    }
  }

  function onPointerMove(event: PointerEvent, chore: Chore): void {
    if (event.pointerId !== pointerId) return;
    const dx = event.clientX - startX;
    const dy = event.clientY - startY;
    if (Math.abs(dx) > TAP_SLOP || Math.abs(dy) > TAP_SLOP) moved = true;
    if (dragId !== chore.id) return;
    if (Math.abs(dy) > Math.abs(dx) * 1.5) return; // vertical scroll, not a swipe
    const base = swipedId === chore.id ? -SWIPE_THRESHOLD : 0;
    dragOffset = Math.max(-SWIPE_THRESHOLD, Math.min(0, base + dx));
  }

  function onPointerUp(event: PointerEvent, chore: Chore): void {
    if (event.pointerId !== pointerId) return;
    pointerId = null;
    const wasDragging = dragId === chore.id;
    const offset = dragOffset;
    dragId = null;
    dragOffset = 0;

    if (wasDragging && moved) {
      swipedId = offset <= -SWIPE_THRESHOLD / 2 ? chore.id : null;
      return;
    }
    if (moved) return;

    // A plain tap.
    if (swipedId === chore.id) {
      swipedId = null;
      return;
    }
    swipedId = null;
    void chores.toggle(chore);
  }

  function onPointerCancel(): void {
    pointerId = null;
    dragId = null;
    dragOffset = 0;
  }

  async function remove(chore: Chore): Promise<void> {
    swipedId = null;
    await chores.hide(chore);
  }

  onMount(() => {
    // Tapping anywhere else resets an open swipe.
    const onDocumentPointerDown = (event: PointerEvent) => {
      if (!swipedId) return;
      const node = event.target as Node | null;
      if (node && root?.contains(node)) return;
      swipedId = null;
    };
    document.addEventListener("pointerdown", onDocumentPointerDown, { capture: true });
    return () =>
      document.removeEventListener("pointerdown", onDocumentPointerDown, { capture: true });
  });
</script>

<section class="glass chores" bind:this={root}>
  <header class="header">
    <h2 class="panel-title">Chores</h2>
    <button type="button" class="add" aria-label="Add chore" onclick={() => (addOpen = true)}>
      +
    </button>
  </header>

  <div class="body">
    {#if chores.error}
      <p class="error">Could not load chores: {chores.error}</p>
    {/if}
    {#if chores.byPerson.length === 0}
      {#if chores.loaded && !chores.error}
        <p class="empty">No chores yet.</p>
      {/if}
    {:else}
      {#each chores.byPerson as group (group.person)}
        <div class="group">
          <h3 class="person">{group.person}</h3>
          <ul class="list">
            {#each group.chores as chore (chore.id)}
              <li class="item" class:completed={chore.status === "completed"}>
                {#if chore.status === "completed"}
                  <button
                    type="button"
                    class="delete"
                    class:revealed={swipedId === chore.id}
                    tabindex={swipedId === chore.id ? 0 : -1}
                    aria-label="Remove chore"
                    aria-hidden={swipedId !== chore.id}
                    onclick={() => remove(chore)}
                  >
                    🗑
                  </button>
                {/if}
                <button
                  type="button"
                  class="row"
                  class:dragging={dragId === chore.id}
                  style:transform="translateX({offsetFor(chore)}px)"
                  aria-pressed={chore.status === "completed"}
                  onpointerdown={(e) => onPointerDown(e, chore)}
                  onpointermove={(e) => onPointerMove(e, chore)}
                  onpointerup={(e) => onPointerUp(e, chore)}
                  onpointercancel={onPointerCancel}
                  oncontextmenu={(e) => e.preventDefault()}
                >
                  <span class="mark" aria-hidden="true">
                    {chore.status === "completed" ? "😊" : "○"}
                  </span>
                  <span class="text">{chore.text}</span>
                </button>
              </li>
            {/each}
          </ul>
        </div>
      {/each}
    {/if}
  </div>
</section>

<AddChoreModal open={addOpen} onclose={() => (addOpen = false)} />

<style>
  .chores {
    display: flex;
    flex-direction: column;
    flex: 2;
    min-height: 0;
    overflow: hidden;
  }
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-shrink: 0;
    padding: 10px 12px 8px;
    border-bottom: 1px solid var(--glass-border);
    background: rgba(0, 0, 0, 0.05);
  }
  .add {
    width: 44px;
    height: 44px;
    border-radius: 10px;
    border: 1px solid rgba(255, 255, 255, 0.2);
    background: rgba(255, 255, 255, 0.1);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    color: var(--text);
    font-size: 1.6em;
    line-height: 1;
    transition:
      background 0.15s ease,
      transform 0.1s ease;
  }
  .add:hover {
    background: rgba(255, 255, 255, 0.2);
  }
  .add:active {
    transform: scale(0.95);
  }
  .body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 6px 12px 12px;
    -webkit-overflow-scrolling: touch;
  }
  .empty,
  .error {
    margin: 8px 0;
    color: var(--text-muted);
  }
  .error {
    color: var(--danger);
  }
  .group {
    margin-bottom: 0.8rem;
  }
  .person {
    margin: 0 0 0.3rem;
    padding: 6px 10px;
    border-radius: var(--radius-sm);
    border: 1px solid rgba(255, 255, 255, 0.15);
    background: rgba(0, 0, 0, 0.25);
    font-size: 1.05em;
    font-weight: 600;
  }
  .list {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .item {
    position: relative;
    margin-bottom: 0.3rem;
    border-radius: var(--radius-sm);
    border: 1px solid rgba(255, 255, 255, 0.08);
    background: rgba(255, 255, 255, 0.05);
    overflow: hidden;
  }
  .row {
    position: relative;
    z-index: 1;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    width: 100%;
    min-height: 44px;
    padding: 8px 10px;
    border-radius: var(--radius-sm);
    background: rgba(30, 30, 40, 0.6);
    color: var(--text);
    font-weight: 500;
    text-align: left;
    text-shadow: var(--text-shadow);
    touch-action: pan-y;
    transition: transform 0.25s ease-out;
  }
  .row.dragging {
    transition: none;
  }
  .row:active {
    background: rgba(255, 255, 255, 0.1);
  }
  .mark {
    flex-shrink: 0;
    font-size: 0.95em;
    font-weight: bold;
  }
  .text {
    flex: 1;
    min-width: 0;
    white-space: normal;
    word-break: break-word;
  }
  .item.completed .row {
    color: #90ee90;
    font-weight: 600;
  }
  .delete {
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    z-index: 0;
    width: 60px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #ff4d4d;
    color: #fff;
    font-size: 18px;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.25s ease-out;
  }
  .delete.revealed {
    opacity: 1;
    pointer-events: auto;
  }
</style>
