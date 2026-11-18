import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { type TripDetailOut, useGetTrip } from "../api/generated";
import { useMe } from "../auth/AuthGate";
import { useShortcuts } from "../platform/shortcuts";
import { QueryState } from "../ui/QueryState";
import { LegsEditor } from "./LegsEditor";
import { ParticipantsEditor } from "./ParticipantsEditor";
import { paths } from "./paths";
import { StopsEditor } from "./StopsEditor";
import { useTripId } from "./TripDetailPage";
import { TripFieldsForm } from "./TripFieldsForm";

/** `/trips/new`: the trip's own fields; once created, the edit page adds people, stops, legs. */
export function TripNewPage() {
  const me = useMe();
  const navigate = useNavigate();
  useShortcuts({ Escape: () => navigate(paths.list) });
  if (me.role === "viewer") {
    return <p className="p-4 text-sm text-red-700">Viewers can't add trips.</p>;
  }
  return (
    <div className="p-4">
      <h2 className="mb-3 text-lg font-semibold">New trip</h2>
      <TripFieldsForm
        onSaved={(trip) => navigate(paths.edit(trip.id), { replace: true })}
        onCancel={() => navigate(paths.list)}
      />
    </div>
  );
}

/** `/trips/:tripId/edit`: everything a core editor changes, each section saving on its own. */
export function TripEditPage() {
  const tripId = useTripId();
  const query = useGetTrip(tripId, { query: { enabled: tripId > 0 } });
  if (tripId === 0) return <p className="p-4 text-sm text-red-700">This trip doesn't exist.</p>;
  return (
    <QueryState query={query} what="trip">
      {(trip) => <TripEditor trip={trip} />}
    </QueryState>
  );
}

function TripEditor({ trip }: { trip: TripDetailOut }) {
  // Saving the fields keeps the editor open: people, stops and legs are usually next.
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  if (!trip.access.edit) {
    return (
      <div className="p-4 text-sm">
        <p className="text-red-700">You can't edit this trip.</p>
        <Link to={paths.trip(trip.id)} className="text-blue-700 hover:underline">
          Back to the trip
        </Link>
      </div>
    );
  }
  return (
    <div className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold">Edit trip</h2>
        <Link
          to={paths.trip(trip.id)}
          className="rounded-md bg-blue-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-800"
        >
          Done
        </Link>
      </div>
      {/* Remount on a trip change so the form starts from the saved values. */}
      <TripFieldsForm key={trip.id} trip={trip} onSaved={() => setSavedAt(new Date())} />
      {savedAt && (
        <p className="mt-1 text-sm text-green-700" role="status">
          Saved at {savedAt.toLocaleTimeString()}.
        </p>
      )}
      <hr className="my-4" />
      <ParticipantsEditor trip={trip} />
      <StopsEditor trip={trip} />
      <LegsEditor trip={trip} />
    </div>
  );
}
