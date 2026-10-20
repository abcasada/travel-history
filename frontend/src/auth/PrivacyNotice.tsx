import { useQueryClient } from "@tanstack/react-query";
import { getGetMeQueryKey, useAcknowledgePrivacyNotice } from "../api/generated";
import { Centered } from "./AuthGate";

/** The honesty notice (PLAN.md §6.7), acknowledged once before using the app. */
export function PrivacyNotice() {
  const queryClient = useQueryClient();
  const acknowledge = useAcknowledgePrivacyNotice({
    mutation: { onSuccess: (me) => queryClient.setQueryData(getGetMeQueryKey(), me) },
  });
  return (
    <Centered>
      <div className="max-w-lg text-left">
        <h1 className="mb-3 text-2xl font-semibold">Before you start: how privacy works here</h1>
        <p className="mb-3">
          Your raw location history is visible only to you. Each trip has its own visibility
          (private, participants, family or public), and the app enforces it everywhere.
        </p>
        <p className="mb-6 font-medium">
          Privacy here is enforced by the app. The server's operator (Adam) has technical access to
          the database and backups and could read anything stored here, including your raw location
          history.
        </p>
        <button
          type="button"
          className="rounded-md bg-blue-700 px-4 py-2 font-medium text-white disabled:opacity-50"
          disabled={acknowledge.isPending}
          onClick={() => acknowledge.mutate()}
        >
          I understand
        </button>
      </div>
    </Centered>
  );
}
