// Turns real input into display activity. Only trusted, user-originated
// events count: `isTrusted` filters out anything dispatched from script, so
// a component can never wake the screen by calling `.click()`.

import { display } from "./stores/display.svelte";

const SOURCES: Record<string, string> = {
  pointerdown: "pointer",
  touchstart: "touch",
  keydown: "keyboard",
  wheel: "wheel",
};

export function installActivityTracking(target: Document = document): () => void {
  const handler = (event: Event) => {
    if (!event.isTrusted) return;
    if (event.type === "pointerdown" && (event as PointerEvent).pointerType === "touch") {
      display.activity("touch");
      return;
    }
    display.activity(SOURCES[event.type] ?? "browser");
  };
  const options: AddEventListenerOptions = { capture: true, passive: true };
  const types = Object.keys(SOURCES);
  for (const type of types) target.addEventListener(type, handler, options);
  return () => {
    for (const type of types) target.removeEventListener(type, handler, options);
  };
}
