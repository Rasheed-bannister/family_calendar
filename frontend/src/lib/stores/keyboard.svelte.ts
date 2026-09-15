// Which text field, if any, the on-screen keyboard is editing.

export type KeyboardTarget = HTMLInputElement | HTMLTextAreaElement;

export interface KeyboardOptions {
  /** Called when the on-screen Enter key is pressed for this target. */
  onEnter?: () => void;
}

class KeyboardStore {
  target = $state<KeyboardTarget | null>(null);
  onEnter = $state<(() => void) | null>(null);

  readonly open = $derived(this.target !== null);

  show(element: KeyboardTarget, options: KeyboardOptions = {}): void {
    this.target = element;
    this.onEnter = options.onEnter ?? null;
  }

  hide(): void {
    this.target = null;
    this.onEnter = null;
  }
}

export const keyboard = new KeyboardStore();
