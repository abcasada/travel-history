import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { uploadFile } from "./chunkedUpload";

type Call = { index: number; size: number; sha: string | null };

/** A tiny in-memory upload server with failure injection. */
function fakeServer(total: number, opts: { failOnce?: number; conflictAt?: number } = {}) {
  const chunk = 4;
  let received = 0;
  let next = 0;
  let failed = false;
  let conflicted = false;
  const calls: Call[] = [];
  const session = () => ({
    id: "u1",
    filename: "Timeline.json",
    kind: "google_timeline",
    total_size: total,
    chunk_size: chunk,
    received_bytes: received,
    next_index: next,
    status: "open",
    import_batch_id: null,
  });
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), "http://localhost").pathname;
    const method = init?.method ?? "GET";
    if (method === "POST" && path === "/api/v1/uploads") return json(session(), 201);
    if (method === "GET" && path === "/api/v1/uploads/u1") return json(session());
    if (method === "POST" && path.endsWith("/complete")) {
      return json(
        {
          id: 9,
          kind: "google_timeline",
          status: "queued",
          summary: {},
          error: "",
          original_name: null,
          size_bytes: null,
          created_at: "",
          finished_at: null,
        },
        202,
      );
    }
    const match = path.match(/chunks\/(\d+)$/);
    if (method === "PUT" && match) {
      const index = Number(match[1]);
      const body = new Uint8Array(init?.body as ArrayBuffer);
      const sha = new Headers(init?.headers).get("X-Chunk-SHA256");
      calls.push({ index, size: body.length, sha });
      if (opts.failOnce === index && !failed) {
        failed = true;
        return json({ detail: "boom" }, 502);
      }
      if (opts.conflictAt === index && !conflicted) {
        conflicted = true; // pretend this chunk already arrived (e.g. from another tab)
        received += body.length;
        next += 1;
        return json({ detail: `expected chunk ${next}` }, 409);
      }
      if (sha !== bytesToHex(sha256(body))) return json({ detail: "checksum" }, 422);
      received += body.length;
      next += 1;
      return json(session());
    }
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls };
}

function file(text: string) {
  return new File([text], "Timeline.json", { type: "application/json" });
}

test("sends fixed-size chunks in order with their checksums", async () => {
  const { calls } = fakeServer(10);
  const progress: number[] = [];
  const batch = await uploadFile(file("0123456789"), "google_timeline", (p) =>
    progress.push(p.sentBytes),
  );
  expect(batch.id).toBe(9);
  expect(calls.map((c) => [c.index, c.size])).toEqual([
    [0, 4],
    [1, 4],
    [2, 2],
  ]);
  expect(progress.at(-1)).toBe(10);
});

test("retries a chunk after a server error", async () => {
  const { calls } = fakeServer(8, { failOnce: 1 });
  await uploadFile(file("abcdefgh"), "google_timeline", () => {}, { retryDelayMs: 0 });
  expect(calls.map((c) => c.index)).toEqual([0, 1, 1]);
});

test("resynchronizes with the server after a conflict", async () => {
  const { calls } = fakeServer(12, { conflictAt: 1 });
  await uploadFile(file("abcdefghijkl"), "google_timeline", () => {}, { retryDelayMs: 0 });
  expect(calls.map((c) => c.index)).toEqual([0, 1, 2]);
});
