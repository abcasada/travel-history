import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { getListImportsQueryKey, type ImportBatchOut, useListImports } from "../api/generated";
import { pickFiles } from "../platform/files";
import { type Progress, uploadFile } from "../upload/chunkedUpload";

const BUSY = new Set(["queued", "processing"]);

type SegmentCounts = {
  total?: number;
  new?: number;
  changed?: number;
  identical?: number;
  absent_kept?: number;
  kept_app_edits?: number;
};
type TimelineSummary = {
  format?: string;
  format_verified?: boolean;
  segments?: SegmentCounts;
  points?: Record<string, { inserted: number; duplicates: number }>;
  trips_flagged_for_review?: number;
  warning_count?: number;
  duplicate_of_batch?: number | null;
  message?: string;
};

export function formatBytes(bytes: number | null) {
  if (bytes === null) return "";
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  if (bytes === 0) return "0 kB";
  return `${Math.max(1, Math.round(bytes / 1e3))} kB`;
}

export function ImportSummary({ batch }: { batch: ImportBatchOut }) {
  const s = batch.summary as TimelineSummary;
  if (batch.status === "duplicate") return <p>This exact file was already imported.</p>;
  if (batch.status === "failed")
    return <p className="text-red-700">Import failed: {batch.error}</p>;
  if (BUSY.has(batch.status)) return <p>Importing…</p>;
  if (!s.segments) return s.message ? <p>{s.message}</p> : null;
  const points = Object.values(s.points ?? {}).reduce((n, p) => n + p.inserted, 0);
  return (
    <ul className="text-sm text-slate-700">
      <li>
        {s.segments.new ?? 0} new, {s.segments.changed ?? 0} changed, {s.segments.identical ?? 0}{" "}
        unchanged segments; {s.segments.absent_kept ?? 0} not in this export were kept
      </li>
      <li>{points.toLocaleString()} location points added</li>
      {(s.segments.kept_app_edits ?? 0) > 0 && (
        <li>{s.segments.kept_app_edits} of your own edits were kept over Google's changes</li>
      )}
      {(s.trips_flagged_for_review ?? 0) > 0 && (
        <li className="text-amber-800">
          {s.trips_flagged_for_review} confirmed trip(s) need review: their data changed
        </li>
      )}
      {s.format_verified === false && (
        <li className="text-amber-800">
          iPhone export: support is not yet verified against a real file. Please check the result.
        </li>
      )}
      {(s.warning_count ?? 0) > 0 && <li>{s.warning_count} malformed records were skipped</li>}
    </ul>
  );
}

export function HistoryPage() {
  const queryClient = useQueryClient();
  const [progress, setProgress] = useState<Progress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const imports = useListImports({
    query: {
      refetchInterval: (query) =>
        query.state.data?.some((b) => BUSY.has(b.status)) || progress ? 3000 : false,
    },
  });

  async function importTimeline() {
    setError(null);
    const [file] = await pickFiles({ accept: ".json,application/json" });
    if (!file) return;
    try {
      setProgress({ sentBytes: 0, totalBytes: file.size });
      await uploadFile(file, "google_timeline", setProgress);
    } catch {
      setError("The upload failed. Check your connection and try again; it will resume.");
    } finally {
      setProgress(null);
      await queryClient.invalidateQueries({ queryKey: getListImportsQueryKey() });
    }
  }

  return (
    <div className="p-4">
      <h2 className="mb-1 text-lg font-semibold">Raw history</h2>
      <p className="mb-3 text-sm text-slate-600">
        Import your Google Timeline export. Re-importing a newer export only adds what changed; the
        original file is always kept unchanged.
      </p>
      <button
        type="button"
        className="rounded-md bg-blue-700 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        onClick={importTimeline}
        disabled={progress !== null}
      >
        Import Google Timeline…
      </button>
      {progress && (
        <div className="mt-3" role="status">
          <progress className="w-full" max={progress.totalBytes} value={progress.sentBytes} />
          <span className="text-sm">
            Uploading {formatBytes(progress.sentBytes)} of {formatBytes(progress.totalBytes)}
          </span>
        </div>
      )}
      {error && <p className="mt-3 text-sm text-red-700">{error}</p>}
      <details className="mt-3 text-sm text-slate-600">
        <summary className="cursor-pointer">How do I export my Timeline?</summary>
        <p className="mt-1">
          Android: Settings → Location → Location services → Timeline → Export Timeline data.
          iPhone: Google Maps → your profile → Your Timeline → ⋯ → Location and privacy settings →
          Export Timeline data. Keep a copy of the file somewhere safe as well.
        </p>
      </details>
      <h3 className="mt-6 mb-2 font-medium">Imports</h3>
      {imports.data?.length === 0 && <p className="text-sm text-slate-600">No imports yet.</p>}
      <ul className="space-y-3">
        {imports.data?.map((batch) => (
          <li key={batch.id} className="rounded border p-3">
            <div className="flex justify-between text-sm">
              <span className="font-medium">{batch.original_name ?? batch.kind}</span>
              <span className="text-slate-500">
                {new Date(batch.created_at).toLocaleString()} · {formatBytes(batch.size_bytes)}
              </span>
            </div>
            <ImportSummary batch={batch} />
          </li>
        ))}
      </ul>
    </div>
  );
}
