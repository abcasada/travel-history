import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import {
  getGetTripSheetTemplateUrl,
  getListImportsQueryKey,
  type ImportBatchOut,
  useListImports,
} from "../api/generated";
import { useMe } from "../auth/AuthGate";
import { formatBytes } from "../pages/History";
import { pickFiles } from "../platform/files";
import { QueryState } from "../ui/QueryState";
import { type Progress, uploadFile } from "../upload/chunkedUpload";
import { importPaths } from "./paths";

export const XLSX_ACCEPT =
  ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

const STATUS_LABELS: Record<string, string> = {
  queued: "Waiting to be read",
  processing: "Reading…",
  preview: "Waiting for you to check and import",
  done: "Imported",
  discarded: "Discarded",
  duplicate: "Same file as an open preview",
  failed: "Couldn't be read",
};

const BUSY = new Set(["queued", "processing"]);

/** Trip spreadsheets (§28.8): the template, an upload button, and the caller's sheet imports.
 * An upload opens its preview, which waits for the worker to read the file. */
export function ImportsPage() {
  const me = useMe();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [progress, setProgress] = useState<Progress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canImport = me.role !== "viewer";
  const imports = useListImports({
    query: {
      enabled: canImport,
      refetchInterval: (query) =>
        query.state.data?.some((b) => b.kind === "trip_sheet" && BUSY.has(b.status)) ? 3000 : false,
    },
  });

  async function upload() {
    setError(null);
    const [file] = await pickFiles({ accept: XLSX_ACCEPT });
    if (!file) return;
    if (!/\.xlsx$/i.test(file.name)) {
      setError("Choose an .xlsx file. Save .xls or .ods sheets as .xlsx first.");
      return;
    }
    let batch: ImportBatchOut | null = null;
    try {
      setProgress({ sentBytes: 0, totalBytes: file.size });
      batch = await uploadFile(file, "trip_sheet", setProgress);
    } catch {
      setError("The upload failed. Check your connection and try again; it will resume.");
    } finally {
      setProgress(null);
      await queryClient.invalidateQueries({ queryKey: getListImportsQueryKey() });
    }
    if (batch) navigate(importPaths.batch(batch.id));
  }

  return (
    <div className="p-4">
      <h2 className="mb-1 text-lg font-semibold">Import trips from a spreadsheet</h2>
      <p className="mb-3 text-sm text-slate-600">
        One trip per tab: its stops, then the legs between them. Nothing changes until you have
        checked the preview and chosen Import. Importing the same sheet again updates the trips it
        made, unless you have edited them here.
      </p>
      {!canImport ? (
        <p className="text-sm text-slate-600">Viewers can't import trips.</p>
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <button
              type="button"
              className="rounded-md bg-blue-700 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
              onClick={upload}
              disabled={progress !== null}
            >
              Upload a trip spreadsheet…
            </button>
            {/* A plain link: the browser downloads the file itself (no JSON API call). */}
            <a
              className="text-sm text-blue-700 hover:underline"
              href={getGetTripSheetTemplateUrl()}
            >
              Download the template (.xlsx)
            </a>
          </div>
          {progress && (
            <div className="mb-3" role="status">
              <progress className="w-full" max={progress.totalBytes} value={progress.sentBytes} />
              <span className="text-sm">
                Uploading {formatBytes(progress.sentBytes)} of {formatBytes(progress.totalBytes)}
              </span>
            </div>
          )}
          {error && (
            <p className="mb-3 text-sm text-red-700" role="alert">
              {error}
            </p>
          )}
          <h3 className="mt-5 mb-2 font-medium">Your spreadsheet imports</h3>
          <QueryState query={imports} what="import list">
            {(batches) => (
              <SheetBatchList batches={batches.filter((b) => b.kind === "trip_sheet")} />
            )}
          </QueryState>
        </>
      )}
    </div>
  );
}

function SheetBatchList({ batches }: { batches: ImportBatchOut[] }) {
  if (batches.length === 0) return <p className="text-sm text-slate-600">No imports yet.</p>;
  return (
    <ul className="divide-y rounded border">
      {batches.map((batch) => (
        <li key={batch.id} data-import-id={batch.id}>
          <Link to={importPaths.batch(batch.id)} className="block px-3 py-2 hover:bg-slate-50">
            <span className="block text-sm font-medium">
              {batch.original_name ?? `Spreadsheet ${batch.id}`}
            </span>
            <span className="block text-xs text-slate-500">
              {STATUS_LABELS[batch.status] ?? batch.status} ·{" "}
              {new Date(batch.created_at).toLocaleString()}
              {batch.size_bytes !== null && ` · ${formatBytes(batch.size_bytes)}`}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
