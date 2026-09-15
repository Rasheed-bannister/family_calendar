<script lang="ts">
  import Modal from "$components/Modal.svelte";
  import { chores } from "$lib/stores/chores.svelte";
  import { keyboard } from "$lib/stores/keyboard.svelte";

  let { open, onclose }: { open: boolean; onclose: () => void } = $props();

  let person = $state("");
  let text = $state("");
  let saving = $state(false);
  let personField = $state<HTMLInputElement | null>(null);
  let textField = $state<HTMLTextAreaElement | null>(null);

  const canSubmit = $derived(person.trim().length > 0 && text.trim().length > 0 && !saving);

  function focusText(): void {
    textField?.focus();
  }

  async function submit(): Promise<void> {
    if (!canSubmit) return;
    saving = true;
    try {
      const ok = await chores.add(person, text);
      if (ok) {
        person = "";
        text = "";
        close();
      }
    } finally {
      saving = false;
    }
  }

  function close(): void {
    keyboard.hide();
    onclose();
  }

  function onSubmit(event: SubmitEvent): void {
    event.preventDefault();
    void submit();
  }

  function onPersonKeydown(event: KeyboardEvent): void {
    if (event.key === "Enter") {
      event.preventDefault();
      focusText();
    }
  }

  // Release the on-screen keyboard whenever the modal goes away.
  $effect(() => {
    if (!open) keyboard.hide();
  });
</script>

<Modal {open} title="Add New Chore" onclose={close} keyboardRoom={keyboard.open}>
  <form class="form" onsubmit={onSubmit}>
    <label class="label" for="chore-person">Person</label>
    <input
      id="chore-person"
      class="field"
      type="text"
      autocomplete="off"
      autocapitalize="words"
      required
      bind:value={person}
      bind:this={personField}
      onfocus={(e) => keyboard.show(e.currentTarget, { onEnter: focusText })}
      onkeydown={onPersonKeydown}
    />

    <label class="label" for="chore-text">Chore</label>
    <textarea
      id="chore-text"
      class="field"
      rows="3"
      autocomplete="off"
      required
      bind:value={text}
      bind:this={textField}
      onfocus={(e) => keyboard.show(e.currentTarget, { onEnter: () => void submit() })}
    ></textarea>

    <div class="actions">
      <button type="button" class="btn" onclick={close}>Cancel</button>
      <button type="submit" class="btn btn-primary" disabled={!canSubmit}>
        {saving ? "Adding…" : "Add Chore"}
      </button>
    </div>
  </form>
</Modal>

<style>
  .form {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .label {
    margin-top: 8px;
    font-weight: 600;
    color: var(--text-muted);
  }
  textarea.field {
    resize: none;
    line-height: 1.4;
  }
  .actions {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    margin-top: 18px;
  }
</style>
