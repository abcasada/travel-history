import { listTrips } from "../api/generated";
import { stubFetch } from "../test/fetch";
import { apiParams, EMPTY_FILTER, readTripFilter, writeTripFilter } from "./filter";

test("the filter round-trips through the URL and keeps other parameters", () => {
  const filter = {
    ...EMPTY_FILTER,
    q: "lake",
    from: "2024-01-01",
    purpose: [3],
    tag: [1, 2],
    mode: ["drive" as const, "flight" as const],
    inView: true,
  };
  const params = writeTripFilter(new URLSearchParams("keep=1"), filter);
  expect(params.toString()).toBe(
    "keep=1&q=lake&from=2024-01-01&purpose=3&tag=1&tag=2&mode=drive&mode=flight&in_view=1",
  );
  expect(readTripFilter(params)).toEqual(filter);
});

test("junk in the URL is ignored", () => {
  const filter = readTripFilter(new URLSearchParams("from=yesterday&tag=x&tag=-1&mode=teleport"));
  expect(filter).toEqual(EMPTY_FILTER);
});

test("only in view sends the map's bbox; empty filters send nothing", () => {
  expect(apiParams(EMPTY_FILTER, "1,2,3,4")).toEqual({});
  expect(apiParams({ ...EMPTY_FILTER, inView: true }, "1,2,3,4")).toEqual({ bbox: "1,2,3,4" });
  expect(apiParams({ ...EMPTY_FILTER, inView: true }, null)).toEqual({});
});

test("the generated client repeats list parameters (any-of), as the API expects", async () => {
  const fetchMock = stubFetch([{ path: "/api/v1/trips", body: { count: 0, items: [] } }]);
  await listTrips({ tag: [1, 2], mode: ["drive", "flight"], purpose: [7] });
  const url = new URL(String(fetchMock.mock.calls[0]?.[0]), "http://localhost");
  expect(url.searchParams.getAll("tag")).toEqual(["1", "2"]);
  expect(url.searchParams.getAll("mode")).toEqual(["drive", "flight"]);
  expect(url.searchParams.getAll("purpose")).toEqual(["7"]);
});
