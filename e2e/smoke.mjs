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
console.log(JSON.stringify({ ok: true, consoleErrors: log }));
await browser.close();
