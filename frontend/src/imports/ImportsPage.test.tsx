import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { pickFiles } from "../platform/files";
import { ME } from "../test/fetch";
import { renderAt } from "../test/render";
import { makeBatch } from "../test/sheets";
import { uploadFile } from "../upload/chunkedUpload";

vi.mock("../platform/files", () => ({ pickFiles: vi.fn(), saveFile: vi.fn() }));
vi.mock("../upload/chunkedUpload", () => ({ uploadFile: vi.fn() }));

const IMPORTS = {
  path: "/api/v1/imports",
  body: [
    makeBatch({ id: 5, status: "preview", original_name: "synthetic-trips.xlsx" }),
    makeBatch({ id: 4, kind: "google_timeline", status: "done", original_name: "Timeline.json" }),
    makeBatch({ id: 3, status: "done", original_name: "older-trips.xlsx" }),
  ],
};

test("lists the caller's spreadsheet imports and links the template", async () => {
  renderAt("/imports", [IMPORTS]);
  const link = await screen.findByRole("link", { name: /synthetic-trips.xlsx/ });
  expect(link).toHaveAttribute("href", "/imports/5");
  expect(link).toHaveTextContent("Waiting for you to check and import");
  expect(screen.getByRole("link", { name: /older-trips.xlsx/ })).toHaveTextContent("Imported");
  // Timeline imports live on the History page.
  expect(screen.queryByText("Timeline.json")).toBeNull();
  expect(screen.getByRole("link", { name: "Download the template (.xlsx)" })).toHaveAttribute(
    "href",
    "/api/v1/trips/sheet-template.xlsx",
  );
});

test("an uploaded sheet opens its preview", async () => {
  const user = userEvent.setup();
  const file = new File(["synthetic"], "synthetic-trips.xlsx");
  vi.mocked(pickFiles).mockResolvedValue([file]);
  vi.mocked(uploadFile).mockResolvedValue(makeBatch({ id: 7, status: "queued" }));
  renderAt("/imports", [IMPORTS, { path: "/api/v1/imports/7", body: makeBatch({ id: 7 }) }]);
  await user.click(await screen.findByRole("button", { name: /Upload a trip spreadsheet/ }));
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/imports/7"));
  expect(uploadFile).toHaveBeenCalledWith(file, "trip_sheet", expect.any(Function));
});

test("only .xlsx files are uploaded", async () => {
  const user = userEvent.setup();
  vi.mocked(uploadFile).mockClear();
  vi.mocked(pickFiles).mockResolvedValue([new File(["x"], "trips.ods")]);
  renderAt("/imports", [IMPORTS]);
  await user.click(await screen.findByRole("button", { name: /Upload a trip spreadsheet/ }));
  expect(await screen.findByText(/Choose an .xlsx file/)).toBeInTheDocument();
  expect(uploadFile).not.toHaveBeenCalled();
});

test("viewers can't import", async () => {
  renderAt("/imports", [IMPORTS], { ...ME, role: "viewer" } as typeof ME);
  expect(await screen.findByText("Viewers can't import trips.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Upload/ })).toBeNull();
});

test("the trip list links to the imports page", async () => {
  renderAt("/trips", [
    { path: "/api/v1/trips", body: { count: 0, items: [] } },
    { path: "/api/v1/trips/map", body: { stops: [], legs: [] } },
  ]);
  expect(await screen.findByRole("link", { name: "Import" })).toHaveAttribute("href", "/imports");
});
