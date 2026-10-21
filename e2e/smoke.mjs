// Browser smoke test (dev stack only: signs in at the mock OIDC provider as dev-member).
// Run with ./dev e2e [base-url]; screenshots land in e2e/out/.
import { chromium } from "playwright-core";
const base = process.argv[2];
const browser = await chromium.connectOverCDP("http://127.0.0.1:9222");
const context = await browser.newContext({ viewport: { width: 1400, height: 850 } });
const page = await context.newPage();
const log = [];
page.on("console", (m) => { if (m.type() === "error") log.push(m.text()); });
try {
await page.goto(`${base}/app/`);
// Production redirects straight to the provider (login wall); the dev server shows the SPA's link.
await page.waitForLoadState("networkidle");
if (!page.url().includes(":8781")) await page.getByRole("link", { name: "Sign in" }).click();
await page.waitForURL(/8781/);
await page.locator("input[name=username]").fill("dev-member");
await page.locator("input[type=submit]").click();
await page.waitForURL(/\/app\//);
const notice = page.getByRole("button", { name: "I understand" });
await notice.waitFor({ timeout: 10000 }).then(() => notice.click(), () => {});
// Headless Chrome has no precise pointer, so the automatic choice is mobile; use the manual switch.
await page.getByText("Dev Member").click();
await page.getByLabel("Layout").selectOption("desktop");
await page.getByRole("link", { name: "Review" }).waitFor();
try {
  await page.locator("canvas.maplibregl-canvas").waitFor({ timeout: 20000 });
} catch (e) {
  await page.screenshot({ path: "out/failure.png" });
  console.log(JSON.stringify({ url: page.url(), consoleErrors: log, body: (await page.locator("body").innerText()).slice(0, 500) }));
  throw e;
}
await page.waitForTimeout(4000);
await page.screenshot({ path: "out/desktop.png" });
await page.keyboard.press("?");
await page.getByRole("dialog", { name: "Keyboard shortcuts" }).waitFor();
await page.keyboard.press("Escape");
// Import a synthetic Timeline through the real UI: picker -> chunked upload -> worker -> summary.
await page.getByRole("link", { name: "History" }).click();
const chooser = page.waitForEvent("filechooser");
await page.getByRole("button", { name: /Import Google Timeline/ }).click();
await (await chooser).setFiles("fixtures/timeline-synthetic.json");
// Wait for this upload to finish, then for the newest import (first in the list) to have a result.
// A re-run of the smoke test uploads the same file again, which is reported as a duplicate.
await page.getByRole("status").waitFor({ state: "detached", timeout: 60000 });
await page
  .locator("li")
  .first()
  .getByText(/(new|unchanged) segments|already imported/)
  .waitFor({ timeout: 60000 });
await page.screenshot({ path: "out/history.png" });
const mobile = await browser.newContext({ viewport: { width: 400, height: 800 }, hasTouch: true, isMobile: true, storageState: await context.storageState() });
const m = await mobile.newPage();
await m.addInitScript(() => localStorage.setItem("shell_override", "mobile"));
await m.goto(`${base}/app/`);
await m.locator("canvas.maplibregl-canvas").waitFor({ timeout: 20000 });
await m.waitForTimeout(3000);
await m.screenshot({ path: "out/mobile.png" });
} catch (e) {
  await page.screenshot({ path: "out/failure.png" }).catch(() => {});
  console.log(JSON.stringify({ failedAt: page.url(), consoleErrors: log, body: (await page.locator("body").innerText().catch(() => "")).slice(0, 400), error: String(e).slice(0, 300) }));
  await browser.close();
  process.exit(1);
}
// Known and harmless: the signed-out /me probe (401), COOP ignored on plain-HTTP dev origins,
// and MapLibre's minified AbortError names logged when tile requests are cancelled.
const benign = [/status of 401/, /Cross-Origin-Opener-Policy/, /^[A-Za-z]{1,3}$/];
const unexpected = log.filter((line) => !benign.some((pattern) => pattern.test(line)));
console.log(JSON.stringify({ ok: true, unexpectedConsoleErrors: unexpected }));
await browser.close();
