// Browser smoke test (dev stack only: signs in at the mock OIDC provider as dev-member).
// Run with ./dev e2e [base-url]; screenshots land in e2e/out/.
import { chromium } from "playwright-core";
const base = process.argv[2];
// Ports come from ./dev e2e (a worktree lane has its own block, D-98).
const cdpPort = process.env.CDP_PORT || "9222";
const oidcPort = process.env.OIDC_PORT || "8781";
const browser = await chromium.connectOverCDP(`http://127.0.0.1:${cdpPort}`);
const context = await browser.newContext({ viewport: { width: 1400, height: 850 } });
const page = await context.newPage();
const log = [];
// An upstream gap, not ours: OpenFreeMap's Noto Sans stacks have no glyphs for U+10400-U+104FF
// (Deseret, Osage), which some OSM place names in the basemap use; MapLibre draws those labels
// without them. Only this exact URL is ignored (checked 2026-11-24: neighbouring ranges are 200).
const glyphGap = "https://tiles.openfreemap.org/fonts/Noto%20Sans%20Regular/66560-66815.pbf";
page.on("console", (m) => { if (m.type() === "error" && m.location().url !== glyphGap) log.push(m.text()); });
// Name the URL of any 404, since the console line alone doesn't say which request failed.
page.on("response", (r) => { if (r.status() === 404 && r.url() !== glyphGap) log.push(`404 ${new URL(r.url()).pathname}`); });
try {
await page.goto(`${base}/app/`);
// Production redirects straight to the provider (login wall); the dev server shows the SPA's link.
await page.waitForLoadState("networkidle");
if (!page.url().includes(`:${oidcPort}`)) await page.getByRole("link", { name: "Sign in" }).click();
await page.waitForURL((u) => u.port === oidcPort);
await page.locator("input[name=username]").fill("dev-member");
await page.locator("input[type=submit]").click();
await page.waitForURL(/\/app\//);
const notice = page.getByRole("button", { name: "I understand" });
await notice.waitFor({ timeout: 10000 }).then(() => notice.click(), () => {});
// Headless Chrome has no precise pointer, so the automatic choice is mobile; use the manual switch.
await page.locator("summary", { hasText: "Dev Member" }).click();
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
// The catalog (work-order item 20): create a trip, add yourself, two stops (typed coordinates
// and a map pick) and a leg between them, view it, edit its title, then delete it.
const tripRequests = [];
page.on("response", (r) => {
  const path = new URL(r.url()).pathname;
  if (/^\/api\/v1\/(trips|legs|stops|persons|me\/person|routing)/.test(path)) tripRequests.push([r.request().method(), path, r.status()]);
});
const title = `E2E trip ${Date.now()}`;
await page.getByRole("link", { name: "Trips" }).click();
await page.getByRole("link", { name: "New trip" }).click();
await page.getByRole("heading", { name: "New trip" }).waitFor();
await page.getByLabel("Title", { exact: true }).fill(title);
await page.getByLabel("Start date").fill("2024-05-01");
await page.getByLabel("End date").fill("2024-05-03");
await page.getByRole("button", { name: "Create trip" }).click();
await page.waitForURL(/\/app\/trips\/\d+\/edit$/);
const tripId = Number(page.url().match(/trips\/(\d+)\/edit/)[1]);
await page.getByRole("button", { name: "Add me" }).click();
await page.getByRole("button", { name: "Remove Dev Member" }).waitFor();
await page.getByRole("button", { name: "Add stop" }).click();
await page.getByLabel("Place name").fill("E2E Start");
await page.getByLabel("Coordinates for the new stop").fill("37.6922, -97.3375");
await page.getByRole("button", { name: "Use", exact: true }).click();
await page.getByRole("form", { name: "New stop" }).getByRole("button", { name: "Add stop" }).click();
await page.getByText("E2E Start", { exact: true }).waitFor();
await page.getByRole("button", { name: "Add stop" }).click();
await page.getByLabel("Place name").fill("E2E End");
await page.getByRole("button", { name: "Pick on map" }).click();
await page.getByText(/Click the map to place/).waitFor();
const canvas = await page.locator("canvas.maplibregl-canvas").boundingBox();
await page.mouse.click(canvas.x + canvas.width * 0.6, canvas.y + canvas.height * 0.4);
await page.getByTestId("place-point").filter({ hasText: /\d+\.\d+, -?\d+\.\d+/ }).waitFor();
await page.getByRole("form", { name: "New stop" }).getByRole("button", { name: "Add stop" }).click();
await page.getByText("E2E End", { exact: true }).waitFor();
// A third stop in Kansas, found by city name in the GeoNames gazetteer (item 14; needs
// `./dev manage load_gazetteer`), so the leg can be routed below. The city names the stop.
await page.getByRole("button", { name: "Add stop" }).click();
await page.getByLabel("City for the new stop").fill("Salina, KS");
await page.getByRole("button", { name: /^Salina, Kansas, United States/ }).click();
if ((await page.getByLabel("Place name").inputValue()) !== "Salina, KS") throw new Error("city did not name the stop");
await page.getByTestId("place-point").filter({ hasText: /^38\.8\d+, -97\.6\d+$/ }).waitFor();
await page.getByRole("form", { name: "New stop" }).getByRole("button", { name: "Add stop" }).click();
await page.getByText("Salina, KS", { exact: true }).waitFor();
await page.getByRole("button", { name: "Add leg" }).click();
await page.getByLabel("From stop").selectOption({ label: "E2E Start" });
await page.getByLabel("To stop").selectOption({ label: "Salina, KS" });
await page.getByRole("form", { name: "New leg" }).getByRole("button", { name: "Add leg" }).click();
await page.getByText(/Drive\s+E2E Start\s+→\s+Salina, KS/).first().waitFor();
await page.getByRole("link", { name: "Done" }).click();
await page.waitForURL(new RegExp(`/app/trips/${tripId}$`));
await page.getByRole("heading", { name: title }).waitFor();
await page.getByRole("region", { name: "Who went" }).getByText("Dev Member").waitFor();
await page.getByRole("region", { name: "Itinerary" }).getByText(/E2E Start → Salina, KS/).waitFor();
await page.waitForTimeout(2000);
await page.screenshot({ path: "out/trip-detail.png" });
// Routing (work-order item 25): propose a road route for the Kansas leg through the routing
// proxy, which must answer from the self-hosted Valhalla; save it as the leg's first version.
await page.getByRole("region", { name: "Itinerary" }).getByRole("link", { name: "Route" }).first().click();
await page.getByRole("button", { name: "Propose a route" }).click();
await page.getByText(/^Proposed: \d+\.\d km/).waitFor({ timeout: 30000 });
await page.getByText(/^By Valhalla \(self-hosted\)/).waitFor();
await page.getByTestId("route-attribution").getByText(/OpenStreetMap/).waitFor();
await page.waitForTimeout(1500);
await page.screenshot({ path: "out/route-proposal.png" });
await page.getByLabel("Note for this version").fill("E2E proposal");
await page.getByRole("button", { name: "Save as a new version" }).click();
await page.getByText(/Version 1 · routed · \d+\.\d km \(current\)/).waitFor();
await page.getByText(/Valhalla \(self-hosted\) [\d.]+.*OpenStreetMap/).waitFor();
// The drag editor (work-order item 26): drag the start anchor of the saved route a little, so
// the span to the next anchor is routed again through the proxy, and save a hand-edited version.
await page.getByRole("button", { name: "Reshape on the map" }).click();
await page.getByTestId("editor-status").getByText(/\d+ points, \d+ fixed/).waitFor();
await page.waitForTimeout(1500);
const box = await page.locator("canvas.maplibregl-canvas").boundingBox();
const [ax, ay] = (await page.evaluate(() => window.__routeEditorAnchors()))[0];
const routesBefore = tripRequests.filter(([m, path]) => m === "POST" && path === "/api/v1/routing/route").length;
await page.mouse.move(box.x + ax, box.y + ay);
await page.mouse.down();
for (let step = 1; step <= 10; step++) await page.mouse.move(box.x + ax + step * 4, box.y + ay + step * 3);
await page.mouse.up();
await page.getByRole("button", { name: "Undo" }).and(page.locator(":enabled")).waitFor({ timeout: 30000 });
const routesAfter = tripRequests.filter(([m, path]) => m === "POST" && path === "/api/v1/routing/route").length;
if (routesAfter !== routesBefore + 1) throw new Error(`editor routed ${routesAfter - routesBefore} times`);
await page.screenshot({ path: "out/route-editor.png" });
// Item 27: a click on an anchor opens its popup (Escape closes it without editing).
await page.waitForTimeout(500);
const [px, py] = (await page.evaluate(() => window.__routeEditorAnchors()))[0];
await page.mouse.click(box.x + px, box.y + py);
await page.getByTestId("route-editor-popup").getByText("Fixed point").waitFor();
await page.getByRole("button", { name: "Remove this point" }).waitFor();
await page.keyboard.press("Escape");
await page.getByTestId("route-editor-popup").waitFor({ state: "detached" });
await page.getByLabel("Note for this version").fill("E2E drag");
await page.getByRole("button", { name: "Save the edited route" }).click();
await page.getByText(/Version 2 · hand_edited · \d+\.\d km \(current\)/).waitFor();
// The version list says what the hand-edited version is made of (Route.sources).
await page.getByTestId("route-sources").filter({ hasText: /Valhalla \(self-hosted\) route, [\d,]+ points, checked/ }).first().waitFor();
await page.getByRole("link", { name: /Back to the trip/ }).click();
await page.getByRole("heading", { name: title }).waitFor();
await page.getByRole("link", { name: "Edit" }).click();
await page.getByRole("heading", { name: "Edit trip" }).waitFor();
await page.getByLabel("Title", { exact: true }).fill(`${title} (edited)`);
await page.getByRole("button", { name: "Save", exact: true }).click();
await page.getByText(/^Saved at /).waitFor();
await page.getByRole("link", { name: "Done" }).click();
await page.getByRole("heading", { name: `${title} (edited)` }).waitFor();
page.once("dialog", (dialog) => dialog.accept());
await page.getByRole("button", { name: "Delete" }).click();
await page.waitForURL(/\/app\/trips$/);
const failedTrips = tripRequests.filter(([, , status]) => status >= 400);
const sawMap = tripRequests.some(([, path]) => path === "/api/v1/trips/map");
const routed = tripRequests.some(([m, path, status]) => m === "POST" && path === "/api/v1/routing/route" && status === 200);
if (failedTrips.length || !sawMap || !routed) throw new Error(`trip requests: ${JSON.stringify(tripRequests.slice(0, 20))}`);
// The list as a working tool (item 21a): two trips made through the API are found with the
// header search ("/"), selected with the keyboard (j, x, Shift+J) and tagged with a new tag in
// one bulk request. The trips and the tag are deleted again.
const api = async (method, path, data) => {
  const token = (await context.cookies()).find((c) => c.name === "csrftoken")?.value ?? "";
  const r = await page.request.fetch(`${base}${path}`, { method, data, headers: { "X-CSRFToken": token } });
  if (!r.ok()) throw new Error(`${method} ${path}: ${r.status()}`);
  return r.status() === 204 ? null : r.json();
};
const bulkTitle = `E2E bulk ${Date.now()}`;
const bulkTag = `e2e-bulk-${Date.now()}`;
const bulkTrips = [
  await api("POST", "/api/v1/trips", { title: `${bulkTitle} A`, start_date: "2023-06-01", end_date: "2023-06-02" }),
  await api("POST", "/api/v1/trips", { title: `${bulkTitle} B`, start_date: "2023-06-03", end_date: "2023-06-04" }),
];
try {
  await page.getByRole("link", { name: "Trips" }).click();
  await page.keyboard.press("/");
  await page.keyboard.type(bulkTitle);
  await page.keyboard.press("Enter");
  await page.getByText("2 trips", { exact: true }).waitFor();
  // Newest first: j puts the cursor on B, x selects it, Shift+J extends the selection to A.
  await page.keyboard.press("j");
  await page.keyboard.press("x");
  await page.keyboard.press("Shift+J");
  await page.getByText("2 selected", { exact: true }).waitFor();
  await page.keyboard.press("t");
  await page.getByLabel("New tag name").fill(bulkTag);
  await page.getByRole("button", { name: "Add tag" }).click();
  await page.getByText("Tag added: 2 trips updated.").waitFor();
  for (const suffix of ["A", "B"]) {
    await page.locator("li", { hasText: `${bulkTitle} ${suffix}` }).getByText(`#${bulkTag}`).waitFor();
  }
  await page.keyboard.press("f");
  await page.waitForTimeout(1000);
  await page.screenshot({ path: "out/trip-list-bulk.png" });
  // Esc closes the tag panel, a second Esc clears the selection.
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  await page.getByText("2 selected", { exact: true }).waitFor({ state: "detached" });
} finally {
  for (const trip of bulkTrips) await api("DELETE", `/api/v1/trips/${trip.id}`).catch(() => {});
  const tag = (await api("GET", "/api/v1/tags")).find((t) => t.name === bulkTag);
  if (tag) await api("DELETE", `/api/v1/tags/${tag.id}`);
}
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
await page.locator("summary", { hasText: "Dev Member" }).click();
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
// Trip spreadsheet import (item 14c-2): upload the SYNTHETIC sheet, check the preview, tick the
// unticked options it offers, commit, open the trip, then delete it. The first run offers
// "create these people" (an unknown person in the sheet); later runs find the trip deleted and
// offer "re-create" instead. Both need the catalog step's Add me (the sheet says "me").
const sheetRequests = [];
page.on("response", (r) => {
  const path = new URL(r.url()).pathname;
  if (/^\/api\/v1\/imports\/\d+\/(trip-sheet|commit)$/.test(path)) sheetRequests.push([r.request().method(), path, r.status()]);
});
await page.getByRole("link", { name: "Trips" }).click();
await page.getByRole("link", { name: "Import", exact: true }).click();
await page.getByRole("heading", { name: "Import trips from a spreadsheet" }).waitFor();
const sheetChooser = page.waitForEvent("filechooser");
await page.getByRole("button", { name: /Upload a trip spreadsheet/ }).click();
await (await sheetChooser).setFiles("fixtures/trip-sheet-synthetic.xlsx");
await page.waitForURL(/\/app\/imports\/\d+$/, { timeout: 60000 });
const sheetCard = page.getByRole("region", { name: "Tab E2E sheet trip" });
const openPreview = page.getByRole("link", { name: "Open that preview" });
// A run that stopped before committing leaves its preview open: the same bytes then point there.
await sheetCard.or(openPreview).first().waitFor({ timeout: 60000 });
if (await openPreview.isVisible()) {
  await openPreview.click();
  await sheetCard.waitFor({ timeout: 30000 });
}
const sheetBatchId = Number(page.url().match(/imports\/(\d+)/)[1]);
for (const option of [/^Create these people: E2E Sheet Cousin/, /^Re-create this trip/]) {
  const box = sheetCard.getByLabel(option);
  if (await box.count()) await box.check();
}
await page.getByRole("button", { name: "Show on map" }).click();
await page.waitForTimeout(2000);
await page.screenshot({ path: "out/trip-sheet-preview.png" });
await page.getByRole("button", { name: "Import 1 trip" }).click();
const sheetResults = page.getByRole("region", { name: "Import results" });
await sheetResults.getByText(/E2E sheet trip: (Imported: new trip|No changes)/).waitFor({ timeout: 30000 });
await sheetCard.getByText(/^(Imported: new trip|No changes)$/).waitFor();
await sheetResults.getByRole("link", { name: "Open" }).click();
await page.getByRole("heading", { name: "E2E sheet trip" }).waitFor();
await page.getByRole("region", { name: "Who went" }).getByText("E2E Sheet Cousin").waitFor();
await page.getByRole("region", { name: "Itinerary" }).getByText(/E2E Sheet Start → E2E Sheet Lake/).first().waitFor();
await page.screenshot({ path: "out/trip-sheet-trip.png" });
// The same preview in the mobile shell (the batch is done now: outcomes, no import button).
await m.goto(`${base}/app/imports/${sheetBatchId}`);
await m.getByRole("region", { name: "Tab E2E sheet trip" }).waitFor({ timeout: 20000 });
await m.waitForTimeout(2000);
await m.screenshot({ path: "out/mobile-trip-sheet.png" });
page.once("dialog", (dialog) => dialog.accept());
await page.getByRole("button", { name: "Delete" }).click();
await page.waitForURL(/\/app\/trips$/);
const failedSheet = sheetRequests.filter(([, , status]) => status >= 400);
const committed = sheetRequests.some(([m, path, status]) => m === "POST" && path.endsWith("/commit") && status === 200);
if (failedSheet.length || !committed) throw new Error(`trip sheet requests: ${JSON.stringify(sheetRequests)}`);
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
