// The hourly provider re-check in the browser (D-108, D-120): `./dev e2e --recheck`, on a stack
// whose .env sets a short OIDC_SESSION_RECHECK_SECONDS (a lane; the dev default 0 is off).
//   1. once the session is due, a save still lands (the grace for writes, D-122), and the next read
//      (opening Trips) sends the SPA straight to the provider (no Sign in screen); the sign-in comes
//      back to the same page and the save is there;
//   2. a second re-check within a minute shows the Sign in screen instead (the loop guard).
// The save is a preference (`e2e_recheck`) of dev-member's, left behind on purpose (harmless).
// The mock provider asks for a user name each time; Authentik answers silently while its own
// session lasts.
import { chromium } from "playwright-core";
const base = process.argv[2];
const cdpPort = process.env.CDP_PORT || "9222";
const oidcPort = process.env.OIDC_PORT || "8781";
const recheck = Number(process.env.RECHECK_SECONDS || "0");
if (!(recheck > 0 && recheck <= 20)) {
  console.log(JSON.stringify({ ok: false, error: `needs OIDC_SESSION_RECHECK_SECONDS between 1 and 20 in .env (got ${recheck})` }));
  process.exit(1);
}
const browser = await chromium.connectOverCDP(`http://127.0.0.1:${cdpPort}`);
const context = await browser.newContext({ viewport: { width: 1400, height: 850 } });
const page = await context.newPage();
const atProvider = (u) => u.port === oidcPort;
async function signInAtProvider() {
  await page.locator("input[name=username]").fill("dev-member");
  await page.locator("input[type=submit]").click();
}
try {
  await page.goto(`${base}/app/`);
  await page.waitForLoadState("networkidle");
  if (!atProvider(new URL(page.url()))) await page.getByRole("link", { name: "Sign in" }).click();
  await page.waitForURL(atProvider);
  await signInAtProvider();
  await page.waitForURL(/\/app\//);
  const signedInAt = Date.now(); // the callback stamped the session just before
  const notice = page.getByRole("button", { name: "I understand" });
  await notice.waitFor({ timeout: 10000 }).then(() => notice.click(), () => {});
  // Headless Chrome gets the mobile shell; the desktop one has the Review link used below.
  await page.locator("summary", { hasText: "Dev Member" }).click();
  await page.getByLabel("Layout").selectOption("desktop");
  // Vehicles makes no API request yet; opening Trips from it does.
  await page.goto(`${base}/app/vehicles?e2e=recheck`);
  await page.getByRole("link", { name: "Trips" }).first().waitFor();
  const logins = [];
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (u.pathname === "/auth/login") logins.push(u.searchParams.get("next"));
  });

  // 1. Due, within the grace (D-122): a save lands and starts nothing.
  await page.waitForTimeout(Math.max(0, signedInAt + (recheck + 2) * 1000 - Date.now()));
  if (Date.now() - signedInAt > (2 * recheck - 2) * 1000) throw new Error("setup took longer than the grace");
  const savedValue = Date.now();
  const saved = await page.evaluate(async (value) => {
    const csrf = document.cookie.split("; ").find((c) => c.startsWith("csrftoken="))?.slice(10) ?? "";
    const response = await fetch("/api/v1/preferences/e2e_recheck", {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": decodeURIComponent(csrf) },
      body: JSON.stringify({ value }),
    });
    return response.status;
  }, savedValue);
  if (saved !== 200) throw new Error(`a save after the check fell due answered ${saved}, not 200`);
  if (logins.length !== 0 || atProvider(new URL(page.url()))) throw new Error("the save started a sign-in");

  // The next read is refused and the SPA goes straight to the provider.
  const sawSignInScreen = page.getByRole("link", { name: "Sign in" }).waitFor({ timeout: 15000 }).then(() => true, () => false);
  await page.getByRole("link", { name: "Trips" }).first().click().catch(() => {});
  await page.waitForURL(atProvider, { timeout: 15000 });
  if (logins.length !== 1 || logins[0] !== "/app/trips") throw new Error(`sign-in redirects: ${JSON.stringify(logins)}`);
  await signInAtProvider();
  await page.waitForURL(/\/app\//);
  const back = new URL(page.url());
  if (back.pathname !== "/app/trips") throw new Error(`came back to ${back.pathname}${back.search}, not /app/trips`);
  if (await sawSignInScreen) throw new Error("the Sign in screen showed before the automatic redirect");
  await page.getByRole("link", { name: "New trip" }).first().waitFor();
  const kept = await page.evaluate(() => fetch("/api/v1/preferences").then((r) => r.json()));
  if (kept.e2e_recheck !== savedValue) throw new Error(`the save is not there: ${JSON.stringify(kept.e2e_recheck)}`);
  await page.screenshot({ path: "out/recheck-back.png" });

  // 2. Due again within a minute of the first redirect: the guard keeps the Sign in screen.
  await page.waitForTimeout((recheck + 3) * 1000);
  await page.reload();
  await page.getByRole("link", { name: "Sign in" }).waitFor({ timeout: 15000 });
  if (logins.length !== 1) throw new Error(`redirected again within a minute: ${JSON.stringify(logins)}`);
  if (atProvider(new URL(page.url()))) throw new Error("redirected again within a minute");
  await page.screenshot({ path: "out/recheck-guard.png" });
} catch (e) {
  await page.screenshot({ path: "out/recheck-failure.png" }).catch(() => {});
  console.log(JSON.stringify({ ok: false, failedAt: page.url(), body: (await page.locator("body").innerText().catch(() => "")).slice(0, 300), error: String(e).slice(0, 300) }));
  await browser.close();
  process.exit(1);
}
console.log(JSON.stringify({ ok: true }));
await browser.close();
