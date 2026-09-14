import { api } from "../api";
import { sse } from "../sse.svelte";
import { toasts } from "./toasts.svelte";
import type { Chore, ChoreStatus } from "../types";

class ChoresStore {
  items = $state<Chore[]>([]);
  loaded = $state(false);
  error = $state<string | null>(null);

  /** Chores grouped by person, in the server's order. */
  readonly byPerson = $derived.by(() => {
    const groups = new Map<string, Chore[]>();
    for (const chore of this.items) {
      const list = groups.get(chore.person) ?? [];
      list.push(chore);
      groups.set(chore.person, list);
    }
    return [...groups.entries()].map(([person, chores]) => ({ person, chores }));
  });

  async load(): Promise<void> {
    try {
      this.items = await api.chores();
      this.error = null;
    } catch (err) {
      this.error = err instanceof Error ? err.message : String(err);
      console.error("Could not load chores", err);
    } finally {
      this.loaded = true;
    }
  }

  /** Optimistic status change; reverts and toasts on failure. */
  async setStatus(id: string, status: ChoreStatus): Promise<boolean> {
    const before = this.items;
    this.items =
      status === "invisible"
        ? before.filter((c) => c.id !== id)
        : before.map((c) => (c.id === id ? { ...c, status } : c));
    try {
      await api.setChoreStatus(id, status);
      return true;
    } catch (err) {
      this.items = before;
      toasts.show("Could not update chore", "error");
      console.error("Could not update chore", err);
      return false;
    }
  }

  toggle(chore: Chore): Promise<boolean> {
    return this.setStatus(chore.id, chore.status === "completed" ? "needsAction" : "completed");
  }

  hide(chore: Chore): Promise<boolean> {
    return this.setStatus(chore.id, "invisible");
  }

  async add(person: string, text: string): Promise<boolean> {
    try {
      const result = await api.addChore(person.trim(), text.trim());
      toasts.show(result.message || "Chore added", "success");
      await this.load();
      return true;
    } catch (err) {
      toasts.show(err instanceof Error ? err.message : "Could not add chore", "error");
      return false;
    }
  }

  start(): () => void {
    void this.load();
    const offChanged = sse.on("chores_changed", () => void this.load());
    const offPoll = sse.onFallbackPoll(() => void this.load());
    return () => {
      offChanged();
      offPoll();
    };
  }
}

export const chores = new ChoresStore();
