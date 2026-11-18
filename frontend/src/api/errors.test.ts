import { ApiError } from "./client";
import { errorKind, errorMessage, fieldErrors } from "./errors";

test("404 never confirms that something exists; 403 uses the server's reason", () => {
  expect(errorMessage(new ApiError(404, { detail: "trip not found" }), "trip")).toBe(
    "This trip doesn't exist or isn't shared with you.",
  );
  expect(errorMessage(new ApiError(403, { detail: "only the owner deletes a trip" }))).toBe(
    "only the owner deletes a trip",
  );
  expect(errorKind(new TypeError("Failed to fetch"))).toBe("network");
});

test("validation errors are keyed by field; plain 422s are a sentence", () => {
  const error = new ApiError(422, {
    detail: [
      { loc: ["body", "payload", "title"], msg: "String should have at least 1 character" },
      { loc: ["body", "payload", "end_date"], msg: "Input should be a valid date" },
    ],
  });
  expect(fieldErrors(error)).toEqual({
    title: "String should have at least 1 character",
    end_date: "Input should be a valid date",
  });
  expect(errorMessage(new ApiError(422, { detail: "unknown stop" }))).toBe("Unknown stop");
  expect(fieldErrors(new ApiError(422, { detail: "unknown stop" }))).toEqual({});
});
