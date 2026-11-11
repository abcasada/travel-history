import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { HistoryLayers } from "../map/HistoryLayers";
import { HistoryMapControls } from "../pages/History";
import { stubFetch } from "../test/fetch";
import { CoverageStrip, shade } from "./CoverageStrip";

const COVERAGE = {
  first_day: "2024-06-01",
  last_day: "2025-03-02",
  days: [
    { day: "2025-03-01", points: 1500, segments: 4 },
    { day: "2025-03-02", points: 0, segments: 1 },
  ],
};

function wrap(node: React.ReactNode, entry = "/history") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

function Search() {
  return <output data-testid="search">{useLocation().search}</output>;
}

test("shades days by how much data they have", () => {
  expect(shade(undefined)).toBe(shade({ day: "", points: 0, segments: 0 }));
  expect(shade({ day: "", points: 0, segments: 2 })).not.toBe(shade(undefined));
  expect(shade({ day: "", points: 5, segments: 0 })).not.toBe(
    shade({ day: "", points: 5000, segments: 0 }),
  );
});

test("draws a year of days and reports clicks", async () => {
  const fetch = stubFetch([{ path: "/api/v1/history/coverage", body: COVERAGE }]);
  const picks: [string, boolean][] = [];
  const { container } = wrap(
    <CoverageStrip from="2025-03-01" to={null} onPick={(d, e) => picks.push([d, e])} />,
  );
  expect(await screen.findByText("2 days with data")).toBeInTheDocument();
  expect(String(fetch.mock.calls[0]?.[0])).toContain("from=2025-01-01");
  expect(container.querySelectorAll("rect[data-day]")).toHaveLength(365);
  const busy = container.querySelector('rect[data-day="2025-03-01"]');
  expect(busy?.getAttribute("fill")).toBe(shade(COVERAGE.days[0]));
  expect(busy?.getAttribute("stroke")).not.toBe("none"); // the selected day
  fireEvent.click(container.querySelector('rect[data-day="2025-03-02"]') as Element, {
    shiftKey: true,
  });
  expect(picks).toEqual([["2025-03-02", true]]);
  expect(screen.getByLabelText("Previous year")).toBeEnabled(); // history starts in 2024
});

test("picking days updates the URL that the map layers read", async () => {
  stubFetch([
    { path: "/api/v1/history/coverage", body: COVERAGE },
    { path: "/api/v1/imports", body: [] },
  ]);
  const { container } = wrap(
    <Routes>
      <Route
        path="/history"
        element={
          <>
            <HistoryMapControls />
            <HistoryLayers />
            <Search />
          </>
        }
      />
    </Routes>,
    "/history?from=2025-03-01&to=2025-03-01",
  );
  await screen.findByText("2 days with data");
  fireEvent.click(container.querySelector('rect[data-day="2025-03-03"]') as Element, {
    shiftKey: true,
  });
  expect(screen.getByTestId("search").textContent).toBe("?from=2025-03-01&to=2025-03-03");
  const tiles = screen.getByTestId("source-history-points").getAttribute("data-tiles") ?? "";
  expect(tiles).toMatch(/\/api\/v1\/history\/tiles\/\{z\}\/\{x\}\/\{y\}\.mvt\?from=/);
  expect(screen.getByTestId("source-history-segments")).toBeInTheDocument();

  fireEvent.click(screen.getByLabelText("Timeline segments"));
  await waitFor(() => expect(screen.queryByTestId("source-history-segments")).toBeNull());
  fireEvent.click(screen.getByText("All dates"));
  expect(screen.getByTestId("search").textContent).toBe("?segments=0");
});

test("history layers appear only on the History route", () => {
  stubFetch([{ path: "/api/v1/imports", body: [] }]);
  wrap(<HistoryLayers />, "/trips");
  expect(screen.queryByTestId("source-history-points")).toBeNull();
});
