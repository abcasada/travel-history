import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { AuthGate } from "../auth/AuthGate";
import { ME, stubFetch } from "../test/fetch";
import { AboutPage } from "./About";

const AIRLINES = {
  name: "openflights_airlines",
  title: "OpenFlights airlines",
  version: "2017-02-02 (5d623a6)",
  source_date: "2017-02-02",
  source_url: "https://raw.githubusercontent.com/jpatokal/openflights/x/data/airlines.dat",
  homepage_url: "https://openflights.org/data.php",
  license: "ODbL 1.0 (database), DbCL 1.0 (contents)",
  license_url: "https://opendatacommons.org/licenses/odbl/1-0/",
  attribution: "Airline and aircraft data: OpenFlights.org (ODbL)",
  row_count: 6161,
  loaded_at: "2026-11-17T20:00:00Z",
};

test("lists datasets with attribution and license links", async () => {
  stubFetch([
    { path: "/api/v1/me", body: ME },
    { path: "/api/v1/reference/datasets", body: [AIRLINES] },
  ]);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AuthGate>
          <AboutPage />
        </AuthGate>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(
    await screen.findByText("Airline and aircraft data: OpenFlights.org (ODbL)"),
  ).toBeInTheDocument();
  const license = screen.getByRole("link", { name: /ODbL 1.0/ });
  expect(license).toHaveAttribute("href", AIRLINES.license_url);
  expect(screen.getByText(/6,161 rows/)).toBeInTheDocument();
});
