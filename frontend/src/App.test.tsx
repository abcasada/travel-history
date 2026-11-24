import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";
import { RECHECK_DETAIL, resetRecheckForTests } from "./auth/recheck";
import { ME, stubFetch } from "./test/fetch";
import { setDesktopMedia } from "./test/media";
import { EMPTY_MAP, makeDetail } from "./test/trips";

function renderApp(path = "/app/") {
  window.history.pushState({}, "", path);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<App queryClient={client} />);
}

test("anonymous visitors get a sign-in link that returns to the page", async () => {
  stubFetch([{ path: "/api/v1/me", status: 401, body: { detail: "authentication required" } }]);
  renderApp();
  const link = await screen.findByRole("link", { name: "Sign in" });
  expect(link).toHaveAttribute("href", "/auth/login?next=%2Fapp%2F");
});

test("the hourly re-check goes straight to sign-in and back to the same page", async () => {
  const navigate = vi.fn();
  resetRecheckForTests(navigate);
  stubFetch([{ path: "/api/v1/me", status: 401, body: { detail: RECHECK_DETAIL } }]);
  renderApp("/app/trips?year=2024");
  expect(await screen.findByText("Signing in again…")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Sign in" })).not.toBeInTheDocument();
  expect(navigate).toHaveBeenCalledWith(
    `/auth/login?next=${encodeURIComponent("/app/trips?year=2024")}`,
  );
});

test("a second re-check within a minute shows the Sign in screen (no redirect loop)", async () => {
  const navigate = vi.fn();
  resetRecheckForTests(navigate);
  window.sessionStorage.setItem("travel.recheckRedirectAt", String(Date.now() - 5_000));
  stubFetch([{ path: "/api/v1/me", status: 401, body: { detail: RECHECK_DETAIL } }]);
  renderApp();
  expect(await screen.findByRole("link", { name: "Sign in" })).toBeInTheDocument();
  expect(navigate).not.toHaveBeenCalled();
});

test("the honesty notice must be acknowledged before the app opens", async () => {
  const fetchMock = stubFetch([
    { path: "/api/v1/me", body: { ...ME, privacy_notice_ack_at: null } },
    { method: "POST", path: "/api/v1/me/privacy-ack", body: ME },
    { path: "/api/v1/preferences", body: {} },
  ]);
  renderApp();
  expect(await screen.findByText(/technical access to the database/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "I understand" }));
  expect(await screen.findByTestId("basemap")).toBeInTheDocument();
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(true);
});

test("desktop shell shows the navigation, list and map side by side", async () => {
  stubFetch([
    { path: "/api/v1/me", body: ME },
    { path: "/api/v1/preferences", body: { split_layout: { list: 40, map: 60 } } },
  ]);
  renderApp();
  expect(await screen.findByRole("link", { name: "Review" })).toBeInTheDocument();
  expect(screen.getByTestId("basemap")).toBeInTheDocument();
  expect(screen.getByText("Your trips")).toBeInTheDocument();
});

test("mobile shell has a tab bar and no review queue link", async () => {
  setDesktopMedia(false);
  stubFetch([{ path: "/api/v1/me", body: ME }]);
  renderApp();
  expect(await screen.findByRole("link", { name: "History" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Review" })).not.toBeInTheDocument();
});

test("? opens the shortcut help on desktop", async () => {
  stubFetch([
    { path: "/api/v1/me", body: ME },
    { path: "/api/v1/preferences", body: {} },
  ]);
  renderApp();
  await screen.findByRole("link", { name: "Review" });
  await userEvent.keyboard("?");
  await waitFor(() =>
    expect(screen.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeInTheDocument(),
  );
});

test("the mobile shell shows a trip's detail under the map", async () => {
  setDesktopMedia(false);
  stubFetch([
    { path: "/api/v1/me", body: ME },
    { path: "/api/v1/trips/10", body: makeDetail() },
    { path: "/api/v1/trips/map", body: EMPTY_MAP },
  ]);
  renderApp("/app/trips/10");
  expect(
    await screen.findByRole("heading", { name: "Synthetic lake weekend" }),
  ).toBeInTheDocument();
  expect(screen.getByTestId("basemap")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Edit" })).toBeInTheDocument();
});
