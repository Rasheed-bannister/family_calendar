#!/usr/bin/env node
// End-to-end smoke test against a running server (default http://localhost:5000).
//
//   npm run smoke                       # headless Chromium, screenshots in ./smoke-out
//   BASE_URL=http://pi.local:5000 npm run smoke
//
// Checks the things that used to break: the UI hides when the server says
// "slideshow", a real click wakes it, and a synthetic click does not.
// Requires `npx playwright install chromium` once.

import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const BASE = process.env.BASE_URL || "http://localhost:5000";
const OUT = process.env.SMOKE_OUT || "smoke-out";
mkdirSync(OUT, { recursive: true });

const results = [];
function check(name, ok, detail = "") {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  (" + detail + ")" : ""}`);
}

// Go through Playwright's HTTP client rather than Node's fetch, which some
// sandboxes and IPv6-first resolvers trip over.
let page;
async function api(path, init = {}) {
  const res =
    init.method === "POST"
      ? await page.request.post(BASE + path)
      : await page.request.get(BASE + path);
  return res.json();
}

const browser = await chromium.launch();
page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => {
  if (m.type() === "error") errors.push(m.text());
});

try {
  await page.goto(BASE + "/", { waitUntil: "networkidle" });
  await page.waitForSelector(".layout", { timeout: 15000 });
  check("app rendered", true);

  const monthTitle = await page.locator("main").innerText();
  check(
    "calendar month visible",
    /\b(January|February|March|April|May|June|July|August|September|October|November|December)\b/.test(
      monthTitle,
    ),
  );

  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/1-active.png` });

  // Server says slideshow -> UI must fade out.
  await api("/api/display/sleep", { method: "POST" });
  await page.waitForFunction(
    () => document.querySelector(".ui")?.classList.contains("hidden"),
    null,
    {
      timeout: 5000,
    },
  );
  await page.waitForTimeout(1200);
  const hiddenOpacity = await page.evaluate(
    () => getComputedStyle(document.querySelector(".ui")).opacity,
  );
  check("UI hidden in slideshow mode", hiddenOpacity === "0", `opacity=${hiddenOpacity}`);
  const hasPhoto = await page.evaluate(
    () => !!document.querySelector(".slideshow img.photo, .slideshow .placeholder"),
  );
  check("slideshow layer present", hasPhoto);
  await page.screenshot({ path: `${OUT}/2-slideshow.png` });

  // A synthetic click must NOT wake the display.
  await page.evaluate(() => document.body.click());
  await page.waitForTimeout(800);
  let snap = await api("/api/display");
  check("synthetic click does not wake", snap.mode === "slideshow", `mode=${snap.mode}`);

  // A real click must.
  await page.mouse.click(640, 400);
  await page.waitForFunction(
    () => !document.querySelector(".ui")?.classList.contains("hidden"),
    null,
    {
      timeout: 5000,
    },
  );
  snap = await api("/api/display");
  check(
    "real click wakes the display",
    snap.mode === "active",
    `source=${snap.last_activity_source}`,
  );
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${OUT}/3-woken.png` });

  // Open the day picker, the QR modal and the add-chore modal to make sure they mount.
  await page.getByRole("button", { name: /Change Date/ }).click();
  check("date picker opens", await page.locator('[role="dialog"]').isVisible());
  await page.screenshot({ path: `${OUT}/4-datepicker.png` });
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: /Photos/ }).click();
  await page.waitForTimeout(800);
  check("QR modal opens", await page.locator('[role="dialog"]').isVisible());
  await page.screenshot({ path: `${OUT}/5-qr.png` });
  await page.keyboard.press("Escape");

  const addButton = page.getByRole("button", { name: /add chore/i });
  if (await addButton.count()) {
    await addButton.first().click();
    await page.waitForTimeout(300);
    const field = page.locator('[role="dialog"] input').first();
    await field.click();
    await page.waitForTimeout(500);
    const kbVisible = await page
      .locator('[aria-label="On-screen keyboard"]')
      .first()
      .isVisible()
      .catch(() => false);
    check("virtual keyboard opens for a field", kbVisible);
    await page.screenshot({ path: `${OUT}/6-keyboard.png` });
    await page.keyboard.press("Escape");
  } else {
    check("add chore button present", false);
  }

  // Settings gear.
  await page.locator("button", { hasText: "⚙" }).first().click();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/7-settings.png` });
  check(
    "settings panel opens",
    await page
      .getByText(/Motion sensor/i)
      .first()
      .isVisible(),
  );

  check("no console/page errors", errors.length === 0, errors.slice(0, 3).join(" | "));
} catch (err) {
  check("smoke run completed", false, String(err));
  await page.screenshot({ path: `${OUT}/error.png` }).catch(() => {});
} finally {
  await browser.close();
}

const failed = results.filter((r) => !r.ok);
console.log(
  `\n${results.length - failed.length}/${results.length} checks passed; screenshots in ${OUT}/`,
);
process.exit(failed.length ? 1 : 0);
