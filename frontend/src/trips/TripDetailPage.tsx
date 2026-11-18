import { Link, useNavigate, useParams } from "react-router";
import {
  type LegOut,
  type StopOut,
  type TripDetailOut,
  useDeleteTrip,
  useGetTrip,
} from "../api/generated";
import { formatDateRange, formatInZone } from "../lib/time";
import { useShortcuts } from "../platform/shortcuts";
import { Button, Section } from "../ui/form";
import { MutationError, QueryState } from "../ui/QueryState";
import { useInvalidateTrip } from "./cache";
import { label, MODE_LABELS, STOP_KIND_LABELS, VISIBILITY_LABELS } from "./labels";
import { paths } from "./paths";

/** Reads `:tripId` from the route; anything that isn't a positive integer is "not found". */
export function useTripId(): number {
  const { tripId } = useParams();
  const id = Number(tripId);
  return Number.isInteger(id) && id > 0 ? id : 0;
}

/** A trip, read-only: header, people, itinerary (legs in order) and stops. */
export function TripDetailPage() {
  const tripId = useTripId();
  const query = useGetTrip(tripId, { query: { enabled: tripId > 0 } });
  if (tripId === 0) return <p className="p-4 text-sm text-red-700">This trip doesn't exist.</p>;
  return (
    <QueryState query={query} what="trip">
      {(trip) => <TripDetail trip={trip} />}
    </QueryState>
  );
}

export function stopName(stops: StopOut[], stopId: number | null | undefined): string {
  const stop = stops.find((s) => s.id === stopId);
  return stop
    ? stop.place.name || `${stop.place.lat.toFixed(3)}, ${stop.place.lon.toFixed(3)}`
    : "";
}

export function legEnds(leg: LegOut, stops: StopOut[]): [string, string] {
  return [
    stopName(stops, leg.origin_stop_id) || leg.origin_label || "?",
    stopName(stops, leg.destination_stop_id) || leg.destination_label || "?",
  ];
}

function TripDetail({ trip }: { trip: TripDetailOut }) {
  const navigate = useNavigate();
  const invalidate = useInvalidateTrip();
  const remove = useDeleteTrip();
  useShortcuts({ e: () => trip.access.edit && navigate(paths.edit(trip.id)) });

  const onDelete = () => {
    if (!window.confirm(`Delete "${trip.title}" with its legs and stops? This can't be undone.`))
      return;
    remove.mutate(
      { tripId: trip.id },
      {
        onSuccess: async () => {
          await invalidate();
          navigate(paths.list);
        },
      },
    );
  };

  return (
    <article className="p-4">
      <Link to={paths.list} className="text-sm text-blue-700 hover:underline">
        ← All trips
      </Link>
      <header className="mt-2 mb-4">
        <div className="flex items-start justify-between gap-2">
          <h2 className="min-w-0 break-words text-xl font-semibold">{trip.title}</h2>
          <div className="flex shrink-0 gap-2">
            {trip.access.edit && (
              <Link
                to={paths.edit(trip.id)}
                className="rounded-md border px-3 py-1.5 text-sm hover:bg-slate-100"
              >
                Edit
              </Link>
            )}
            {trip.access.delete && (
              <Button variant="danger" onClick={onDelete} disabled={remove.isPending}>
                Delete
              </Button>
            )}
          </div>
        </div>
        <p className="text-sm text-slate-600">
          {formatDateRange(trip.start_date, trip.end_date)}
          {trip.purpose && ` · ${trip.purpose.name}`} · {label(VISIBILITY_LABELS, trip.visibility)}
          {!trip.is_owner && ` · by ${trip.owner.display_name}`}
        </p>
        {trip.tags.length > 0 && (
          <p className="mt-1 flex flex-wrap gap-2 text-sm text-blue-800">
            {trip.tags.map((t) => (
              <span key={`${t.id}-${t.author.id}`}>#{t.name}</span>
            ))}
          </p>
        )}
        <MutationError error={remove.error} what="trip" />
      </header>
      {trip.notes && <p className="mb-4 whitespace-pre-wrap text-sm">{trip.notes}</p>}
      <Section title="Who went">
        {trip.participants.length === 0 ? (
          <p className="text-sm text-slate-600">Nobody recorded yet.</p>
        ) : (
          <ul className="flex flex-wrap gap-2 text-sm">
            {trip.participants.map((p) => (
              <li key={p.person.id} className="rounded-full bg-slate-100 px-2 py-0.5">
                {p.person.display_name}
                {!p.on_trip && <span className="text-slate-500"> (some legs)</span>}
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title="Itinerary">
        {trip.legs.length === 0 ? (
          <p className="text-sm text-slate-600">No legs yet.</p>
        ) : (
          <ol className="space-y-2">
            {trip.legs.map((leg) => (
              <LegRow key={leg.id} leg={leg} trip={trip} />
            ))}
          </ol>
        )}
      </Section>
      <Section title="Stops">
        {trip.stops.length === 0 ? (
          <p className="text-sm text-slate-600">No stops yet.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {trip.stops.map((stop) => (
              <li key={stop.id}>
                <span className="font-medium">{stop.place.name || "Unnamed place"}</span>{" "}
                <span className="text-slate-500">
                  {label(STOP_KIND_LABELS, stop.kind)}
                  {stop.arrive_utc && ` · ${formatInZone(stop.arrive_utc, stop.tz)}`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </article>
  );
}

function LegRow({ leg, trip }: { leg: LegOut; trip: TripDetailOut }) {
  const [from, to] = legEnds(leg, trip.stops);
  const people = trip.participants
    .filter((p) => leg.participant_ids.includes(p.person.id))
    .map((p) => p.person.display_name);
  return (
    <li className="rounded border px-3 py-2 text-sm">
      <div className="flex items-baseline justify-between gap-2">
        <span>
          <span className="font-medium">{label(MODE_LABELS, leg.mode)}</span> {from} → {to}
          {leg.flight_number && <span className="text-slate-500"> · {leg.flight_number}</span>}
        </span>
        <Link
          to={paths.legRoute(trip.id, leg.id)}
          className="text-xs text-blue-700 hover:underline"
        >
          Route
        </Link>
      </div>
      {leg.start_utc && (
        <p className="text-xs text-slate-500">
          {formatInZone(leg.start_utc, leg.start_tz)}
          {leg.end_utc && ` → ${formatInZone(leg.end_utc, leg.end_tz)}`}
        </p>
      )}
      {people.length > 0 && <p className="text-xs text-slate-500">{people.join(", ")}</p>}
    </li>
  );
}
