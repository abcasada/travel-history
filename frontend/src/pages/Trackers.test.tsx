import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";
import { AuthGate } from "../auth/AuthGate";
import { ME, type Route, stubFetch } from "../test/fetch";
import { TrackersPage } from "./Trackers";

const SECRET = `trk_${"S".repeat(43)}`;
const QR = "data:image/svg+xml;base64,PHN2Zy8+";

const PHONE = {
  id: 7,
  name: "Synthetic phone",
  kind: "owntracks",
  token_prefix: "trk_AbCd",
  created_at: "2026-11-01T10:00:00Z",
  last_used_at: "2026-11-02T10:00:00Z",
  revoked_at: null,
  points_received: 1234,
};
const OLD = {
  ...PHONE,
  id: 3,
  name: "Old tablet",
  token_prefix: "trk_Zz9_",
  revoked_at: "2026-10-01T00:00:00Z",
};

function renderPage(routes: Route[], me = ME) {
  const fetchMock = stubFetch([{ path: "/api/v1/me", body: me }, ...routes]);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/trackers"]}>
        <AuthGate>
          <TrackersPage />
        </AuthGate>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return fetchMock;
}

test("lists tokens by prefix only, with revoke for active ones", async () => {
  renderPage([{ path: "/api/v1/tracking/tokens", body: [PHONE, OLD] }]);
  expect(await screen.findByText("Synthetic phone")).toBeInTheDocument();
  expect(screen.getByText("trk_AbCd…")).toBeInTheDocument();
  expect(screen.getByText(/1,234 points/)).toBeInTheDocument();
  expect(screen.getByText(/Revoked/)).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Revoke" })).toHaveLength(1);
});

test("creating a token shows it once with its setup link and QR code", async () => {
  const user = userEvent.setup();
  const fetchMock = renderPage([
    { path: "/api/v1/tracking/tokens", body: [] },
    {
      method: "POST",
      path: "/api/v1/tracking/tokens",
      status: 201,
      body: {
        device: { ...PHONE, kind: "overland", last_used_at: null, points_received: 0 },
        token: SECRET,
        setup: {
          tracker: "overland",
          endpoint: "https://tracker.example.test/api/v1/ingest/overland",
          auth: "bearer",
          username: null,
          link: `overland://setup?url=x&token=${SECRET}`,
          link_qr: QR,
          token_qr: QR,
          body_template: null,
          content_type: "application/json",
        },
      },
    },
  ]);
  await user.type(await screen.findByLabelText("Name"), "Synthetic phone");
  await user.selectOptions(screen.getByLabelText("App"), "overland");
  await user.click(screen.getByRole("button", { name: "Create token" }));

  expect(await screen.findByLabelText("Token")).toHaveValue(SECRET);
  expect(screen.getByRole("link", { name: "Open in Overland" })).toHaveAttribute(
    "href",
    `overland://setup?url=x&token=${SECRET}`,
  );
  expect(screen.getByAltText("Setup QR code")).toHaveAttribute("src", QR);
  expect(screen.getByText(/only time the token is shown/)).toBeInTheDocument();
  const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
  expect(JSON.parse(String(post?.[1]?.body))).toEqual({
    name: "Synthetic phone",
    kind: "overland",
  });

  await user.click(screen.getByRole("button", { name: /Done, hide the token/ }));
  expect(screen.queryByLabelText("Token")).not.toBeInTheDocument();
  expect(document.body.textContent).not.toContain(SECRET);
});

test("GPSLogger setup shows the fields to copy instead of a link", async () => {
  const user = userEvent.setup();
  renderPage([
    { path: "/api/v1/tracking/tokens", body: [] },
    {
      method: "POST",
      path: "/api/v1/tracking/tokens",
      status: 201,
      body: {
        device: { ...PHONE, kind: "gpslogger" },
        token: SECRET,
        setup: {
          tracker: "gpslogger",
          endpoint: "https://tracker.example.test/api/v1/ingest/owntracks",
          auth: "basic",
          username: "travel",
          link: null,
          link_qr: null,
          token_qr: QR,
          body_template: '{"_type":"location","lat":%LAT}',
          content_type: "application/json",
        },
      },
    },
  ]);
  await user.type(await screen.findByLabelText("Name"), "p");
  await user.selectOptions(screen.getByLabelText("App"), "gpslogger");
  await user.click(screen.getByRole("button", { name: "Create token" }));
  expect(await screen.findByText(/user name "travel"/)).toBeInTheDocument();
  expect(screen.getByText('{"_type":"location","lat":%LAT}')).toBeInTheDocument();
  expect(screen.queryByAltText("Setup QR code")).not.toBeInTheDocument();
});

test("revoking asks first, then calls the API", async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    "confirm",
    vi.fn(() => true),
  );
  const fetchMock = renderPage([
    { path: "/api/v1/tracking/tokens", body: [PHONE] },
    {
      method: "POST",
      path: "/api/v1/tracking/tokens/7/revoke",
      body: { ...PHONE, revoked_at: "2026-11-03T00:00:00Z" },
    },
  ]);
  await user.click(await screen.findByRole("button", { name: "Revoke" }));
  expect(window.confirm).toHaveBeenCalled();
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).endsWith("/api/v1/tracking/tokens/7/revoke"),
      ),
    ).toBe(true),
  );
});

test("viewers can't create tokens", async () => {
  renderPage([{ path: "/api/v1/tracking/tokens", body: [] }], { ...ME, role: "viewer" });
  expect(await screen.findByText(/Viewers don't record location history/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Create token" })).not.toBeInTheDocument();
});
