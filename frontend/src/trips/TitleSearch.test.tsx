import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter, useLocation, useNavigate, useSearchParams } from "react-router";
import { readTripFilter, writeTripFilter } from "./filter";
import { TitleSearch } from "./TripFilters";

/** A parent whose `q` catches up a moment after each keystroke, as the URL does in a browser. */
function Lagging({ seen }: { seen: string[] }) {
  const [q, setQ] = useState("");
  seen.push(q);
  return <TitleSearch q={q} onSearch={(next) => setTimeout(() => setQ(next), 30)} />;
}

test("fast typing keeps every letter while the URL lags behind", async () => {
  // delay: null types every key before any 30 ms update lands, like fast typing in a browser.
  const user = userEvent.setup({ delay: null });
  const seen: string[] = [];
  render(<Lagging seen={seen} />);
  const box = screen.getByRole("searchbox", { name: "Search trip titles" });
  await user.type(box, "Synthetic weekend");
  expect(box).toHaveValue("Synthetic weekend");
  await waitFor(() => expect(seen.at(-1)).toBe("Synthetic weekend"));
  expect(box).toHaveValue("Synthetic weekend");
});

/** Wired like TripFilters: the box edits the list's `q` and keeps the other filters. */
function Wired() {
  const [params, setParams] = useSearchParams();
  const filter = readTripFilter(params);
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <TitleSearch
        q={filter.q}
        onSearch={(q) => setParams(writeTripFilter(params, { ...filter, q }), { replace: true })}
      />
      <output data-testid="location">{location.pathname + location.search}</output>
      <button type="button" onClick={() => navigate("/trips?mode=drive")}>
        Clear
      </button>
    </>
  );
}

test("on the router, fast typing reaches the URL whole and Clear filters empties the box", async () => {
  const user = userEvent.setup({ delay: null });
  render(
    <MemoryRouter initialEntries={["/trips?mode=drive"]}>
      <Wired />
    </MemoryRouter>,
  );
  const box = screen.getByRole("searchbox", { name: "Search trip titles" });
  await user.type(box, "Synthetic weekend");
  expect(box).toHaveValue("Synthetic weekend");
  expect(screen.getByTestId("location")).toHaveTextContent("/trips?q=Synthetic+weekend&mode=drive");
  await user.click(screen.getByRole("button", { name: "Clear" }));
  expect(box).toHaveValue("");
});
