import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { ApiError } from "../api/client";
import { errorKind, errorMessage } from "../api/errors";
import {
  getGetImportQueryKey,
  getGetTripSheetPreviewQueryKey,
  getListImportsQueryKey,
  type ImportBatchOut,
  type SheetTabResultOut,
  type TripSheetPreviewOut,
  useCommitTripSheet,
  useDiscardTripSheet,
  useGetImport,
  useGetTripSheetPreview,
} from "../api/generated";
import { saveFile } from "../platform/files";
import { invalidateTrip } from "../trips/cache";
import { paths } from "../trips/paths";
import { Button } from "../ui/form";
import { MutationError, QueryState } from "../ui/QueryState";
import { importPaths, selectedTab } from "./paths";
import {
  type Choices,
  COMMITTED_LABELS,
  commitBody,
  emptyChoices,
  included,
  issueCounts,
  reportCsv,
  reportName,
} from "./sheet";
import { IssueTable, TabCard } from "./TabCard";

const BUSY = new Set(["queued", "processing"]);
const HAS_PREVIEW = new Set(["preview", "done", "discarded"]);

function useBatchId(): number | null {
  const id = Number(useParams().batchId);
  return Number.isInteger(id) && id > 0 ? id : null;
}

/** `/imports/:id`: waits for the worker to read the sheet, then shows the preview (§28.8). */
export function TripSheetPreviewPage() {
  const id = useBatchId();
  if (id === null) {
    return <p className="p-4 text-sm text-red-700">This import doesn't exist.</p>;
  }
  return <BatchPage id={id} />;
}

function BatchPage({ id }: { id: number }) {
  const batch = useGetImport(id, {
    query: {
      refetchInterval: (query) => (BUSY.has(query.state.data?.status ?? "") ? 1500 : false),
    },
  });
  return (
    <div className="p-4">
      <Link to={importPaths.list} className="text-sm text-blue-700 hover:underline">
        ← Spreadsheet imports
      </Link>
      <QueryState query={batch} what="import">
        {(data) => <BatchState batch={data} />}
      </QueryState>
    </div>
  );
}

function BatchState({ batch }: { batch: ImportBatchOut }) {
  const name = batch.original_name ?? `Spreadsheet ${batch.id}`;
  if (batch.kind !== "trip_sheet") {
    return <p className="mt-3 text-sm">This import isn't a trip spreadsheet.</p>;
  }
  if (BUSY.has(batch.status)) {
    return (
      <p className="mt-3 text-sm" role="status">
        Reading {name}…
      </p>
    );
  }
  if (batch.status === "failed") {
    return (
      <div className="mt-3" role="alert">
        <h2 className="text-lg font-semibold">{name}</h2>
        <p className="text-sm text-red-700">This file couldn't be read: {batch.error}</p>
      </div>
    );
  }
  if (batch.status === "duplicate") {
    const open = (batch.summary as { duplicate_of_batch?: number | null }).duplicate_of_batch;
    return (
      <div className="mt-3">
        <h2 className="text-lg font-semibold">{name}</h2>
        <p className="text-sm">
          This exact file is already waiting for you in an open preview.{" "}
          {open ? (
            <Link className="text-blue-700 hover:underline" to={importPaths.batch(open)}>
              Open that preview
            </Link>
          ) : null}
        </p>
      </div>
    );
  }
  if (!HAS_PREVIEW.has(batch.status)) {
    return <p className="mt-3 text-sm">This import is {batch.status}.</p>;
  }
  return <Preview batchId={batch.id} />;
}

function Preview({ batchId }: { batchId: number }) {
  const preview = useGetTripSheetPreview(batchId);
  return (
    <QueryState query={preview} what="preview">
      {(data) => <PreviewBody preview={data} />}
    </QueryState>
  );
}

function PreviewBody({ preview }: { preview: TripSheetPreviewOut }) {
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [choices, setChoices] = useState<Choices>(emptyChoices);
  const [notice, setNotice] = useState<string | null>(null);
  const [results, setResults] = useState<SheetTabResultOut[] | null>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const commit = useCommitTripSheet();
  const discard = useDiscardTripSheet();
  const id = preview.batch_id;
  const batchOpen = preview.status === "preview";
  const openTab = selectedTab(params);
  const counts = issueCounts(preview);
  const chosen = preview.tabs.filter((tab) => included(tab, choices));
  const tabName = (recordId: number) =>
    preview.tabs.find((t) => t.record_id === recordId)?.tab ?? `#${recordId}`;

  async function refresh() {
    await Promise.all(
      [getGetTripSheetPreviewQueryKey(id), getGetImportQueryKey(id), getListImportsQueryKey()].map(
        (queryKey) => queryClient.invalidateQueries({ queryKey }),
      ),
    );
  }

  function showOnMap(recordId: number) {
    const next = new URLSearchParams(params);
    next.set("tab", String(recordId));
    setParams(next, { replace: true });
  }

  function onCommit() {
    setNotice(null);
    setResults(null);
    commit.mutate(
      { batchId: id, data: commitBody(preview, choices) },
      {
        onSuccess: async (result) => {
          setResults(result.results);
          setChoices(emptyChoices());
          // The bar that was clicked sits at the bottom; the results are at the top.
          resultsRef.current?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
          // Every trip list, the trip map and each trip the commit wrote.
          const tripIds = new Set(result.results.flatMap((r) => (r.trip_id ? [r.trip_id] : [])));
          await Promise.all([
            invalidateTrip(queryClient),
            ...[...tripIds].map((tripId) => invalidateTrip(queryClient, tripId)),
            refresh(),
          ]);
        },
        onError: async (error) => {
          const records =
            error instanceof ApiError
              ? ((error.body as { records?: number[] } | undefined)?.records ?? [])
              : [];
          const kind = errorKind(error);
          if (kind === "conflict" && records.length) {
            setNotice(
              `Changed in the app since this preview: ${records.map(tabName).join(", ")}. The preview has been refreshed; check it and import again.`,
            );
          } else if (kind === "invalid" && records.length) {
            setNotice(
              `Can't be imported as it is now: ${records.map(tabName).join(", ")}. The preview has been refreshed; untick that tab or fix the sheet.`,
            );
          } else {
            setNotice(errorMessage(error, "import"));
          }
          if (kind === "conflict" || kind === "invalid") await refresh();
        },
      },
    );
  }

  function onDiscard() {
    if (!window.confirm("Discard this import? No trips are changed; the file stays archived.")) {
      return;
    }
    discard.mutate({ batchId: id }, { onSuccess: () => void refresh() });
  }

  const busy = commit.isPending || discard.isPending;
  return (
    <div className="mt-2">
      <h2 className="text-lg font-semibold break-words">
        {preview.original_name ?? `Spreadsheet ${id}`}
      </h2>
      <p className="mb-2 text-sm text-slate-600">
        {preview.status === "done"
          ? "Imported."
          : preview.status === "discarded"
            ? "Discarded: nothing was imported."
            : "Check each tab, then import. Nothing has changed yet."}{" "}
        {preview.tabs.length === 1 ? "1 trip tab" : `${preview.tabs.length} trip tabs`}
        {counts.problems > 0 && `, ${counts.problems} problem${counts.problems === 1 ? "" : "s"}`}
        {counts.warnings > 0 && `, ${counts.warnings} warning${counts.warnings === 1 ? "" : "s"}`}.
      </p>
      {counts.total > 0 && (
        <div className="mb-3">
          <Button
            onClick={() =>
              saveFile(reportName(preview.original_name, id), reportCsv(preview), "text/csv")
            }
          >
            Download report (CSV)
          </Button>
        </div>
      )}
      {preview.workbook_issues.length > 0 && (
        <IssueTable issues={preview.workbook_issues} caption="Workbook issues" />
      )}
      {preview.tabs.length === 0 && (
        <p className="text-sm text-slate-600">
          No trip tabs found. Tabs named Instructions or starting with _ are skipped.
        </p>
      )}

      <div ref={resultsRef}>{results && <CommitResults results={results} />}</div>

      {preview.tabs.map((tab) => (
        <TabCard
          key={tab.record_id}
          tab={tab}
          open={openTab === tab.record_id}
          batchOpen={batchOpen}
          choices={choices}
          onChoices={setChoices}
          onShowOnMap={() => showOnMap(tab.record_id)}
        />
      ))}

      {/* One bar, kept in view at the bottom of the list pane however long the sheet is. */}
      {(batchOpen || notice) && (
        <div className="sticky bottom-0 -mx-4 border-t bg-white px-4 py-3">
          {notice && (
            <p className="mb-2 text-sm text-red-700" role="alert">
              {notice}
            </p>
          )}
          <MutationError error={discard.error} what="import" />
          {batchOpen && (
            <CommitBar
              count={chosen.length}
              busy={busy}
              onCommit={onCommit}
              onDiscard={onDiscard}
            />
          )}
        </div>
      )}
    </div>
  );
}

function CommitBar({
  count,
  busy,
  onCommit,
  onDiscard,
}: {
  count: number;
  busy: boolean;
  onCommit: () => void;
  onDiscard: () => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      <Button variant="primary" onClick={onCommit} disabled={busy || count === 0}>
        {count === 1 ? "Import 1 trip" : `Import ${count} trips`}
      </Button>
      <Button variant="danger" onClick={onDiscard} disabled={busy}>
        Discard
      </Button>
    </div>
  );
}

function CommitResults({ results }: { results: SheetTabResultOut[] }) {
  return (
    <section
      aria-label="Import results"
      className="mb-3 rounded border border-green-300 bg-green-50 p-3"
    >
      <h3 className="mb-1 text-sm font-medium text-green-900">Import finished</h3>
      {results.length === 0 && <p className="text-sm">No tabs were imported.</p>}
      <ul className="text-sm">
        {results.map((result) => (
          <li key={result.record_id}>
            {result.tab}: {COMMITTED_LABELS[result.outcome] ?? result.outcome}
            {result.message && ` (${result.message})`}
            {result.trip_id !== null && (
              <>
                {" "}
                <Link className="text-blue-700 hover:underline" to={paths.trip(result.trip_id)}>
                  Open
                </Link>
              </>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
