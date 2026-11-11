import { addDays, parseDay, readFilter, tileQuery, writeFilter } from "./filter";

test("reads a valid filter and ignores junk", () => {
  expect(readFilter(new URLSearchParams("from=2025-03-01&to=2025-03-31"))).toEqual({
    from: "2025-03-01",
    to: "2025-03-31",
    segments: true,
  });
  expect(readFilter(new URLSearchParams("from=yesterday&segments=0"))).toEqual({
    from: null,
    to: null,
    segments: false,
  });
  // A backwards range is swapped rather than showing nothing.
  expect(readFilter(new URLSearchParams("from=2025-03-31&to=2025-03-01")).from).toBe("2025-03-01");
});

test("writes the filter back, keeping other params", () => {
  const next = writeFilter(new URLSearchParams("x=1&to=2020-01-01"), {
    from: "2025-03-01",
    to: null,
    segments: false,
  });
  expect(next.toString()).toBe("x=1&from=2025-03-01&segments=0");
});

test("tile query covers whole local days as instants", () => {
  const query = new URLSearchParams(
    tileQuery({ from: "2025-03-01", to: "2025-03-01", segments: true }, "2.7").slice(1),
  );
  const from = new Date(query.get("from") ?? "");
  const to = new Date(query.get("to") ?? "");
  expect(from.getTime()).toBe(parseDay("2025-03-01").getTime());
  expect(to.getTime()).toBe(parseDay("2025-03-02").getTime());
  expect(query.get("rev")).toBe("2.7");
  expect(tileQuery({ from: null, to: null, segments: true })).toBe("");
});

test("adds days across month ends", () => {
  expect(addDays("2024-02-28", 1)).toBe("2024-02-29");
  expect(addDays("2025-12-31", 1)).toBe("2026-01-01");
});
