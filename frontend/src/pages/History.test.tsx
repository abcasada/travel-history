import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { stubFetch } from "../test/fetch";
import { formatBytes, HistoryPage } from "./History";

const base = {
  kind: "google_timeline",
  error: "",
  created_at: "2026-10-20T10:00:00Z",
  finished_at: "2026-10-20T10:01:00Z",
  size_bytes: 2_000_000,
};

test("lists imports with readable summaries", async () => {
  stubFetch([
    {
      path: "/api/v1/imports",
      body: [
        {
          ...base,
          id: 2,
          status: "done",
          original_name: "Timeline.json",
          summary: {
            format: "ios",
            format_verified: false,
            segments: { new: 3, changed: 1, identical: 40, absent_kept: 2, kept_app_edits: 1 },
            points: { google_path: { inserted: 1200, duplicates: 5 } },
            trips_flagged_for_review: 1,
            warning_count: 0,
          },
        },
        { ...base, id: 1, status: "duplicate", original_name: "Timeline (1).json", summary: {} },
      ],
    },
  ]);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <HistoryPage />
    </QueryClientProvider>,
  );
  expect(await screen.findByText(/3 new, 1 changed, 40 unchanged segments/)).toBeInTheDocument();
  expect(screen.getByText(/1,200 location points added/)).toBeInTheDocument();
  expect(screen.getByText(/1 confirmed trip\(s\) need review/)).toBeInTheDocument();
  expect(screen.getByText(/iPhone export/)).toBeInTheDocument();
  expect(screen.getByText(/already imported/)).toBeInTheDocument();
});

test("formats byte counts", () => {
  expect(formatBytes(0)).toBe("0 kB");
  expect(formatBytes(400)).toBe("1 kB");
  expect(formatBytes(25_000)).toBe("25 kB");
  expect(formatBytes(2_500_000)).toBe("2.5 MB");
});
