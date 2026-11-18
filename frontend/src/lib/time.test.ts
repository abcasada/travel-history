import { formatDate, utcToZoned, zonedToUtc } from "./time";

test("local wall-clock time in a zone converts to UTC and back", () => {
  // Chicago: CDT (UTC-5) in summer, CST (UTC-6) in winter.
  expect(zonedToUtc("2024-07-04T09:30", "America/Chicago")).toBe("2024-07-04T14:30:00Z");
  expect(zonedToUtc("2024-01-15T09:30", "America/Chicago")).toBe("2024-01-15T15:30:00Z");
  expect(utcToZoned("2024-07-04T14:30:00Z", "America/Chicago")).toBe("2024-07-04T09:30");
  // Half-hour offsets and the date line.
  expect(zonedToUtc("2024-03-01T00:15", "Asia/Kolkata")).toBe("2024-02-29T18:45:00Z");
  expect(utcToZoned("2024-02-29T18:45:00Z", "Pacific/Auckland")).toBe("2024-03-01T07:45");
});

test("a time skipped by the spring-forward gap lands just after it", () => {
  // 02:30 doesn't exist in Chicago on 2024-03-10; it becomes 03:30 CDT.
  expect(utcToZoned(zonedToUtc("2024-03-10T02:30", "America/Chicago"), "America/Chicago")).toBe(
    "2024-03-10T03:30",
  );
});

test("dates display without shifting by the browser's zone", () => {
  expect(formatDate("2024-05-01")).toMatch(/2024/);
  expect(formatDate("2024-05-01")).toMatch(/1/);
});

test("a repeated fall-back hour means its first occurrence", () => {
  expect(zonedToUtc("2024-11-03T01:30", "America/Chicago")).toBe("2024-11-03T06:30:00Z");
});
