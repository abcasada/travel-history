import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router";
import { HeaderSearch } from "./HeaderSearch";

function Probe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname + location.search}</output>;
}

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <HeaderSearch />
      <Probe />
    </MemoryRouter>,
  );
}

test("on the trip list it edits the list's q and keeps the other filters", async () => {
  const user = userEvent.setup();
  renderAt("/trips?mode=drive&q=la");
  const box = screen.getByRole("searchbox", { name: "Search trips" });
  expect(box).toHaveValue("la");
  await user.type(box, "ke");
  expect(screen.getByTestId("location")).toHaveTextContent("/trips?q=lake&mode=drive");
  await user.clear(box);
  expect(screen.getByTestId("location")).toHaveTextContent(/^\/trips\?mode=drive$/);
});

test("on the map home it filters the list shown there", async () => {
  const user = userEvent.setup();
  renderAt("/");
  await user.type(screen.getByRole("searchbox", { name: "Search trips" }), "x");
  expect(screen.getByTestId("location")).toHaveTextContent(/^\/\?q=x$/);
});

test("from another page, typing opens the trip list with that search", async () => {
  const user = userEvent.setup();
  renderAt("/history?from=2024-01-01");
  const box = screen.getByRole("searchbox", { name: "Search trips" });
  expect(box).toHaveValue("");
  await user.type(box, "c");
  expect(screen.getByTestId("location")).toHaveTextContent(/^\/trips\?q=c$/);
});

test("Enter and Esc leave the box so list keys work again", async () => {
  const user = userEvent.setup();
  renderAt("/trips");
  const box = screen.getByRole("searchbox", { name: "Search trips" });
  await user.click(box);
  await user.keyboard("{Enter}");
  expect(box).not.toHaveFocus();
  await user.click(box);
  await user.keyboard("{Escape}");
  expect(box).not.toHaveFocus();
});
