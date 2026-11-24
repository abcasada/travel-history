import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import {
  type LegOut,
  type ParticipantOut,
  type StopOut,
  type TripDetailOut,
  useDeleteLeg,
  useDeleteTrip,
  useGetTrip,
  useSetParticipantConsent,
} from "../api/generated";
import { formatDateRange, formatInZone } from "../lib/time";
import { useShortcuts } from "../platform/shortcuts";
import { Button, Section } from "../ui/form";
import { MutationError, QueryState } from "../ui/QueryState";
import { useInvalidateTrip } from "./cache";
import { airlineLabel } from "./inputs";
import { MyLegToggle } from "./LegPeople";
import { LegForm } from "./LegsEditor";
import { CABIN_LABELS, label, MODE_LABELS, STOP_KIND_LABELS, VISIBILITY_LABELS } from "./labels";
import { NotesSection } from "./NotesSection";
import { paths } from "./paths";
import { TripTags } from "./TripTags";

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
    stopName(stops, leg.origin_stop_id) || leg.origin_label || leg.origin_airport?.code || "?",
    stopName(stops, leg.destination_stop_id) ||
      leg.destination_label ||
      leg.destination_airport?.code ||
      "?",
  ];
}

/** "SYN → XS01 · SY 123 · seat 12A · Economy" for a flight leg; "" otherwise. */
export function flightDetails(leg: LegOut): string {
  if (leg.mode !== "flight") return "";
  const codes =
    leg.origin_airport || leg.destination_airport
      ? `${leg.origin_airport?.code ?? "?"} → ${leg.destination_airport?.code ?? "?"}`
      : "";
  const flight = [leg.airline?.code, leg.flight_number].filter(Boolean).join(" ");
  return [
    codes,
    flight || (leg.airline ? airlineLabel(leg.airline) : ""),
    leg.seat && `seat ${leg.seat}`,
    leg.cabin_class && label(CABIN_LABELS, leg.cabin_class),
  ]
    .filter(Boolean)
    .join(" · ");
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
        <TripTags trip={trip} />
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
                {p.can_set_consent && <ConsentToggle trip={trip} participant={p} />}
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Itinerary trip={trip} />
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
                {stop.notes && (
                  <p className="whitespace-pre-wrap text-xs text-slate-600">{stop.notes}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>
      <NotesSection trip={trip} />
    </article>
  );
}

/** Whether this person's name (and their notes, photos, legs) may appear on a public page once
 * public pages exist (T37). Only the person's managing user sees the switch. */
function ConsentToggle({
  trip,
  participant,
}: {
  trip: TripDetailOut;
  participant: ParticipantOut;
}) {
  const invalidate = useInvalidateTrip();
  const set = useSetParticipantConsent();
  return (
    <label className="ml-2 inline-flex items-center gap-1 text-xs text-slate-600">
      <input
        type="checkbox"
        aria-label={`${participant.person.display_name} may appear on public pages`}
        checked={participant.public_consent === true}
        disabled={set.isPending}
        onChange={(e) =>
          set.mutate(
            {
              tripId: trip.id,
              personId: participant.person.id,
              data: { public_consent: e.target.checked },
            },
            { onSuccess: () => invalidate(trip.id) },
          )
        }
      />
      public
      <MutationError error={set.error} what="consent" />
    </label>
  );
}

/** The legs in order. Participants who may contribute add their own legs here and edit or
 * delete them (core legs are edited on the edit page). */
function Itinerary({ trip }: { trip: TripDetailOut }) {
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const contributes = trip.access.add_leg === "contribution";
  return (
    <Section
      title="Itinerary"
      actions={
        contributes &&
        editing === null && (
          <Button onClick={() => setEditing("new")} aria-label="Add my leg">
            + My leg
          </Button>
        )
      }
    >
      {trip.legs.length === 0 && editing !== "new" ? (
        <p className="text-sm text-slate-600">No legs yet.</p>
      ) : (
        <ol className="space-y-2">
          {trip.legs.map((leg) =>
            editing === leg.id ? (
              <li key={leg.id}>
                <LegForm trip={trip} leg={leg} onDone={() => setEditing(null)} />
              </li>
            ) : (
              <LegRow
                key={leg.id}
                leg={leg}
                trip={trip}
                onEdit={editing === null ? () => setEditing(leg.id) : undefined}
              />
            ),
          )}
        </ol>
      )}
      {editing === "new" && <LegForm trip={trip} onDone={() => setEditing(null)} />}
    </Section>
  );
}

function LegRow({ leg, trip, onEdit }: { leg: LegOut; trip: TripDetailOut; onEdit?: () => void }) {
  const invalidate = useInvalidateTrip();
  const remove = useDeleteLeg();
  const [from, to] = legEnds(leg, trip.stops);
  const name = `${label(MODE_LABELS, leg.mode)} ${from} to ${to}`;
  const people = trip.participants
    .filter((p) => leg.participant_ids.includes(p.person.id))
    .map((p) => p.person.display_name);
  // Core legs are changed on the edit page; contributed legs right here, by their author.
  const own = leg.is_contribution;
  const flight = flightDetails(leg);
  return (
    <li className="rounded border px-3 py-2 text-sm">
      <div className="flex items-baseline justify-between gap-2">
        <span>
          <span className="font-medium">{label(MODE_LABELS, leg.mode)}</span> {from} → {to}
          {leg.is_contribution && (
            <span className="text-slate-500"> · added by {leg.author.display_name}</span>
          )}
        </span>
        <span className="flex shrink-0 items-center gap-2 text-xs">
          <Link to={paths.legRoute(trip.id, leg.id)} className="text-blue-700 hover:underline">
            Route
          </Link>
          {own && leg.can_edit && onEdit && (
            <Button variant="link" aria-label={`Edit ${name}`} onClick={onEdit}>
              Edit
            </Button>
          )}
          {own && leg.can_delete && (
            <Button
              variant="link"
              aria-label={`Delete ${name}`}
              disabled={remove.isPending}
              onClick={() => {
                if (!window.confirm(`Delete the leg ${from} to ${to}?`)) return;
                remove.mutate({ legId: leg.id }, { onSuccess: () => invalidate(trip.id) });
              }}
            >
              Delete
            </Button>
          )}
        </span>
      </div>
      {flight && <p className="text-xs text-slate-600">{flight}</p>}
      {leg.start_utc && (
        <p className="text-xs text-slate-500">
          {formatInZone(leg.start_utc, leg.start_tz)}
          {leg.end_utc && ` → ${formatInZone(leg.end_utc, leg.end_tz)}`}
        </p>
      )}
      {people.length > 0 && <p className="text-xs text-slate-500">{people.join(", ")}</p>}
      {leg.notes && <p className="mt-1 whitespace-pre-wrap text-xs">{leg.notes}</p>}
      <MyLegToggle trip={trip} leg={leg} name={name} />
      <MutationError error={remove.error} what="leg" />
    </li>
  );
}
