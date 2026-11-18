import type { UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { errorKind, errorMessage } from "../api/errors";

/**
 * Renders a query's loading and error states and, once loaded, its data. Every page that loads
 * one thing by id uses this, so 404 ("doesn't exist or isn't shared with you") and 403 read the
 * same everywhere.
 */
export function QueryState<T>({
  query,
  what,
  children,
}: {
  query: UseQueryResult<T, unknown>;
  what: string;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) {
    return (
      <p className="p-4 text-sm text-slate-500" role="status">
        Loading…
      </p>
    );
  }
  if (query.isError) {
    const kind = errorKind(query.error);
    return (
      <div className="p-4" role="alert">
        <p className="text-sm text-red-700">{errorMessage(query.error, what)}</p>
        {(kind === "server" || kind === "network") && (
          <button
            type="button"
            className="mt-2 rounded border px-2 py-1 text-sm hover:bg-slate-100"
            onClick={() => void query.refetch()}
          >
            Try again
          </button>
        )}
      </div>
    );
  }
  return <>{children(query.data)}</>;
}

/** An inline error line for a failed mutation (null renders nothing). */
export function MutationError({ error, what }: { error: unknown; what: string }) {
  if (!error) return null;
  return (
    <p className="text-sm text-red-700" role="alert">
      {errorMessage(error, what)}
    </p>
  );
}
