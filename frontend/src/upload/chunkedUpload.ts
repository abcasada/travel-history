/**
 * Resumable chunked upload (PLAN.md §17, D-65): create a session, send fixed-size chunks in order
 * with their SHA-256, then complete. Network failures are retried; if the server expects a
 * different chunk (e.g. after a reload), the upload resynchronizes from the server's position.
 * SHA-256 comes from @noble/hashes because WebCrypto is unavailable on plain-HTTP pages.
 */
import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { ApiError, apiFetch } from "../api/client";
import {
  completeUpload,
  createUpload,
  getUpload,
  type ImportBatchOut,
  type Kind,
  type UploadOut,
} from "../api/generated";

export type Progress = { sentBytes: number; totalBytes: number };

const MAX_ATTEMPTS = 5;

async function sleep(ms: number) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function putChunk(uploadId: string, index: number, bytes: Uint8Array): Promise<UploadOut> {
  return apiFetch<UploadOut>(`/api/v1/uploads/${uploadId}/chunks/${index}`, {
    method: "PUT",
    body: bytes as BodyInit,
    headers: {
      "Content-Type": "application/octet-stream",
      "X-Chunk-SHA256": bytesToHex(sha256(bytes)),
    },
  });
}

export async function uploadFile(
  file: Blob & { name: string; type: string },
  kind: Kind,
  onProgress: (progress: Progress) => void = () => {},
  options: { retryDelayMs?: number } = {},
): Promise<ImportBatchOut> {
  const retryDelay = options.retryDelayMs ?? 1000;
  let session = await createUpload({
    filename: file.name,
    size: file.size,
    kind,
    content_type: file.type,
  });
  onProgress({ sentBytes: session.received_bytes, totalBytes: file.size });
  while (session.received_bytes < file.size) {
    const start = session.received_bytes;
    const bytes = new Uint8Array(await file.slice(start, start + session.chunk_size).arrayBuffer());
    for (let attempt = 1; ; attempt++) {
      try {
        session = await putChunk(session.id, session.next_index, bytes);
        break;
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          session = await getUpload(session.id); // resynchronize with the server's position
          break;
        }
        const retryable = !(error instanceof ApiError) || error.status >= 500;
        if (!retryable || attempt >= MAX_ATTEMPTS) throw error;
        await sleep(retryDelay * attempt);
      }
    }
    onProgress({ sentBytes: session.received_bytes, totalBytes: file.size });
  }
  return completeUpload(session.id);
}
