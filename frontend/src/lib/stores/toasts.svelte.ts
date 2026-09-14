export type ToastKind = "info" | "success" | "error";

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

class ToastStore {
  items = $state<Toast[]>([]);
  private seq = 0;

  show(message: string, kind: ToastKind = "info", durationMs = 3000): void {
    const id = ++this.seq;
    this.items = [...this.items, { id, kind, message }];
    setTimeout(() => this.dismiss(id), durationMs);
  }

  dismiss(id: number): void {
    this.items = this.items.filter((t) => t.id !== id);
  }
}

export const toasts = new ToastStore();
