import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter, useLocation, useNavigate, useSearchParams } from "react-router";
import { afterEach, vi } from "vitest";
import { readTripFilter, writeTripFilter } from "./filter";
import { TitleSearch } from "./TripFilters";

afterEach(() => {
  vi.useRealTimers();
});

/** A parent whose `q` catches up 30 ms after each keystroke, as a lagging URL would. */
function Lagging({ seen }: { seen: string[] }) {
  const [q, setQ] = useState("");
  seen.push(q);
  return <TitleSearch q={q} onSearch={(next) => setTimeout(() => setQ(next), 30)} />;
}

test("fast typing keeps every letter while the URL lags behind", () => {
  // Fake timers fix the interleaving: a key every 10 ms, so each URL update lands three keys
  // late, mid-typing. Those stale values are the box's own echoes and must not reset it. Keys
  // go in with fireEvent (synchronous) because user-event's async wrapper waits on a real timer.
  vi.useFakeTimers();
  const seen: string[] = [];
  render(<Lagging seen={seen} />);
  const box = screen.getByRole<HTMLInputElement>("searchbox", { name: "Search trip titles" });
  for (const key of "Synthetic weekend") {
    // Each key extends what the box shows now, as a real keystroke would.
    fireEvent.change(box, { target: { value: box.value + key } });
    act(() => vi.advanceTimersByTime(10));
  }
  expect(seen).toContain("Synth");
  expect(box).toHaveValue("Synthetic weekend");
  act(() => vi.advanceTimersByTime(100));
  expect(seen.at(-1)).toBe("Synthetic weekend");
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

test("a space typed over the text stays, though the URL drops a blank search", async () => {
  const user = userEvent.setup({ delay: null });
  render(
    <MemoryRouter initialEntries={["/trips?q=a"]}>
      <Wired />
    </MemoryRouter>,
  );
  const box = screen.getByRole("searchbox", { name: "Search trip titles" });
  await user.type(box, " ", { initialSelectionStart: 0, initialSelectionEnd: 1 });
  expect(screen.getByTestId("location")).toHaveTextContent(/^\/trips$/);
  expect(box).toHaveValue(" ");
  await user.type(box, "x");
  expect(box).toHaveValue(" x");
  expect(screen.getByTestId("location")).toHaveTextContent("/trips?q=+x");
});
