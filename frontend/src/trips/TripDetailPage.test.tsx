import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderAt, requests } from "../test/render";
import { EMPTY_MAP, makeDetail, makeLeg, makeParticipant, makeStop } from "../test/trips";

const MAP = { path: "/api/v1/trips/map", body: EMPTY_MAP };

const TRIP = makeDetail({
  participants: [makeParticipant(7, "Synthetic Parent"), makeParticipant(8, "Synthetic Kid")],
  stops: [
    makeStop(),
    makeStop({ id: 101, place: { ...makeStop().place, id: 501, name: "Synthetic Motel" } }),
  ],
  legs: [
    makeLeg({
      origin_stop_id: 101,
      destination_stop_id: 100,
      participant_ids: [7],
      start_utc: "2024-05-01T14:00:00Z",
      start_tz: "America/Chicago",
    }),
    makeLeg({
      id: 201,
      sequence: 2,
      mode: "flight",
      origin_label: "SYA",
      destination_label: "SYB",
      flight_number: "SY 12",
    }),
  ],
});

test("shows who went, the itinerary in order and the stops", async () => {
  renderAt("/trips/10", [MAP, { path: "/api/v1/trips/10", body: TRIP }]);
  expect(
    await screen.findByRole("heading", { name: "Synthetic lake weekend" }),
  ).toBeInTheDocument();
  const people = screen.getByRole("region", { name: "Who went" });
  expect(people).toHaveTextContent("Synthetic Parent");
  expect(people).toHaveTextContent("Synthetic Kid");
  const legs = screen.getByRole("region", { name: "Itinerary" });
  expect(legs).toHaveTextContent(/Drive\s*Synthetic Motel → Synthetic Lake/);
  expect(legs).toHaveTextContent(/Flight\s*SYA → SYB · SY 12/);
  expect(legs).toHaveTextContent("Synthetic Parent");
  expect(screen.getAllByRole("link", { name: "Route" })[0]).toHaveAttribute(
    "href",
    "/trips/10/legs/200/route",
  );
  expect(screen.getByRole("link", { name: "Edit" })).toHaveAttribute("href", "/trips/10/edit");
});

test("a trip the caller can't see reads as not found, without retrying", async () => {
  const { fetchMock } = renderAt("/trips/99", [
    MAP,
    { path: "/api/v1/trips/99", status: 404, body: { detail: "trip not found" } },
  ]);
  expect(
    await screen.findByText("This trip doesn't exist or isn't shared with you."),
  ).toBeInTheDocument();
  expect(requests(fetchMock).filter((r) => r === "GET /api/v1/trips/99")).toHaveLength(1);
});

test("without edit or delete access there are no Edit or Delete controls", async () => {
  const readOnly = makeDetail({
    is_owner: false,
    access: { edit: false, delete: false, contribute: false, add_leg: null },
  });
  renderAt("/trips/10", [MAP, { path: "/api/v1/trips/10", body: readOnly }]);
  await screen.findByRole("heading", { name: "Synthetic lake weekend" });
  expect(screen.queryByRole("link", { name: "Edit" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
});

test("e opens the editor; deleting asks first and returns to the list", async () => {
  const user = userEvent.setup();
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  const { fetchMock } = renderAt("/trips/10", [
    MAP,
    { path: "/api/v1/trips/10", body: TRIP },
    { method: "DELETE", path: "/api/v1/trips/10", status: 204 },
    { path: "/api/v1/trips", body: { count: 0, items: [] } },
  ]);
  await screen.findByRole("heading", { name: "Synthetic lake weekend" });
  await user.keyboard("e");
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/trips/10/edit"));
  await user.click(await screen.findByRole("link", { name: "Done" }));
  await user.click(await screen.findByRole("button", { name: "Delete" }));
  expect(confirm).toHaveBeenCalled();
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent(/^\/trips$/));
  expect(requests(fetchMock)).toContain("DELETE /api/v1/trips/10");
});
