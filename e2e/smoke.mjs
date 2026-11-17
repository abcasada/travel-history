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
// The raw-history map (milestone 2.3): point and segment tiles and the coverage strip load for
// the signed-in user, with no failed history requests.
const historyRequests = [];
page.on("response", (r) => {
  const path = new URL(r.url()).pathname;
  if (path.startsWith("/api/v1/history/")) historyRequests.push([path, r.status()]);
});
await page.goto(`${base}/app/history?from=2025-03-01&to=2025-03-02`);
await page.getByRole("img", { name: /Days with location history/ }).waitFor({ timeout: 20000 });
await page.locator("canvas.maplibregl-canvas").waitFor({ timeout: 20000 });
await page.waitForTimeout(4000);
await page.screenshot({ path: "out/history-map.png" });
const failed = historyRequests.filter(([, status]) => status >= 400);
const sawTiles = historyRequests.some(([path]) => path.startsWith("/api/v1/history/tiles/"));
const sawCoverage = historyRequests.some(([path]) => path === "/api/v1/history/coverage");
if (failed.length || !sawTiles || !sawCoverage) {
  throw new Error(`history map requests: ${JSON.stringify(historyRequests.slice(0, 12))}`);
}
const mobile = await browser.newContext({ viewport: { width: 400, height: 800 }, hasTouch: true, isMobile: true, storageState: await context.storageState() });
const m = await mobile.newPage();
await m.addInitScript(() => localStorage.setItem("shell_override", "mobile"));
await m.goto(`${base}/app/`);
await m.locator("canvas.maplibregl-canvas").waitFor({ timeout: 20000 });
await m.waitForTimeout(3000);
await m.screenshot({ path: "out/mobile.png" });
await m.goto(`${base}/app/history?from=2025-03-01&to=2025-03-02`);
await m.getByRole("img", { name: /Days with location history/ }).waitFor({ timeout: 20000 });
await m.waitForTimeout(3000);
await m.screenshot({ path: "out/mobile-history.png" });
// Tracker ingestion (milestone 2.4): create a token on the trackers page, send one synthetic
// OwnTracks point with it, revoke it, and check the endpoint then refuses it. Each run leaves one
// revoked token and one point (Wichita city centre) in dev-member's history.
await page.getByText("Dev Member").click();
await page.getByRole("link", { name: "Location trackers" }).click();
await page.getByLabel("Name").fill("E2E phone");
await page.getByRole("button", { name: "Create token" }).click();
await page.getByAltText("Setup QR code").waitFor({ timeout: 10000 });
await page.screenshot({ path: "out/trackers.png" });
const secret = await page.getByLabel("Token").inputValue();
const point = { _type: "location", lat: 37.6922, lon: -97.3375, tst: Math.floor(Date.now() / 1000) - 60 };
const send = () => page.request.post(`${base}/api/v1/ingest/owntracks`, {
  data: point, headers: { Authorization: `Bearer ${secret}` },
});
const sent = await send();
if (sent.status() !== 200 || (await sent.text()) !== "[]") throw new Error(`ingest: ${sent.status()}`);
await page.getByRole("button", { name: /Done, hide the token/ }).click();
page.once("dialog", (dialog) => dialog.accept());
await page.locator("li", { hasText: "E2E phone" }).first().getByRole("button", { name: "Revoke" }).click();
await page.locator("li", { hasText: "E2E phone" }).first().getByText(/Revoked/).waitFor();
const refused = await send();
if (refused.status() !== 401) throw new Error(`revoked token answered ${refused.status()}`);
// Import a synthetic Timeline through the real UI: picker -> chunked upload -> worker -> summary.
await page.getByRole("link", { name: "History" }).click();
const chooser = page.waitForEvent("filechooser");
await page.getByRole("button", { name: /Import Google Timeline/ }).click();
// The batch id comes from this upload's own completion response, so the check below can't be
// satisfied by an earlier run's batch. A re-run uploads the same file again, which is reported
// as a duplicate.
const completed = page.waitForResponse(
  (r) => /\/api\/v1\/uploads\/[^/]+\/complete$/.test(r.url()) && r.request().method() === "POST",
  { timeout: 60000 },
);
await (await chooser).setFiles("fixtures/timeline-synthetic.json");
const completion = await completed;
if (completion.status() !== 202) throw new Error(`upload complete: ${completion.status()}`);
const batchId = (await completion.json()).id;
await page.getByRole("status").waitFor({ state: "detached", timeout: 60000 });
await page
  .locator(`li[data-import-id="${batchId}"]`)
  .getByText(/(new|unchanged) segments|already imported/)
  .waitFor({ timeout: 60000 });
await page.screenshot({ path: "out/history.png" });
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
