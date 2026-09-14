import { beforeEach, describe, expect, it, vi } from "vitest";

const snapshot = (mode: "active" | "dimmed" | "slideshow") => ({
  mode,
  brightness: mode === "active" ? 1 : 0.5,
  overlay_brightness: mode === "active" ? 1 : 0.5,
  is_night: false,
  idle_seconds: 0,
  last_activity_source: null,
  last_activity_at: null,
  thresholds: { dim_after_seconds: 10, hide_ui_after_seconds: 20, brightness: 0.5 },
  backlight: { backend: "none", available: false },
});

const activity = vi.fn();
vi.mock("../api", () => ({
  api: {
    display: vi.fn(async () => snapshot("active")),
    activity: (...args: unknown[]) => activity(...args),
    sleep: vi.fn(async () => snapshot("slideshow")),
  },
}));
vi.mock("../sse.svelte", () => ({
  sse: { on: () => () => {}, onFallbackPoll: () => () => {} },
}));

describe("display store", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    activity.mockReset();
    activity.mockImplementation(async () => snapshot("active"));
  });

  it("reflects the server snapshot", async () => {
    const { display } = await import("./display.svelte");
    display.apply(snapshot("slideshow"));
    expect(display.mode).toBe("slideshow");
    expect(display.uiVisible).toBe(false);
    expect(display.dimmed).toBe(true);
    display.apply(snapshot("active"));
    expect(display.uiVisible).toBe(true);
  });

  it("sends the first activity at once and collapses a burst into one more", async () => {
    const { display } = await import("./display.svelte");
    display.activity("touch");
    display.activity("pointer");
    display.activity("keyboard");
    expect(activity).toHaveBeenCalledTimes(1);
    expect(activity).toHaveBeenCalledWith("touch");
    await vi.advanceTimersByTimeAsync(2_000);
    expect(activity).toHaveBeenCalledTimes(2);
    expect(activity).toHaveBeenLastCalledWith("keyboard");
  });
});
