import { type FormEvent, useState } from "react";
import { Link } from "react-router";
import { fieldErrors } from "../api/errors";
import {
  type AirlineRef,
  type AirportRef,
  type CabinClass,
  type LegIn,
  type LegOut,
  type TravelMode,
  type TripDetailOut,
  useCreateLeg,
  useDeleteLeg,
  useReorderLegs,
  useUpdateLeg,
} from "../api/generated";
import { browserZone, isValidZone, utcToZoned, zonedToUtc } from "../lib/time";
import { Button, Field, inputClass, Section } from "../ui/form";
import { MutationError } from "../ui/QueryState";
import { useInvalidateTrip } from "./cache";
import { AirlineSearch, AirportSearch, airlineLabel, airportLabel, ZonedTimeInput } from "./inputs";
import { LegPeople } from "./LegPeople";
import { CABIN_LABELS, MODE_LABELS, MODES } from "./labels";
import { paths } from "./paths";
import { legEnds, stopName } from "./TripDetailPage";

export type LegValues = {
  mode: TravelMode;
  origin_stop_id: string;
  destination_stop_id: string;
  origin_label: string;
  destination_label: string;
  start: string;
  start_tz: string;
  end: string;
  end_tz: string;
  flight_number: string;
  origin_airport: AirportRef | null;
  destination_airport: AirportRef | null;
  airline: AirlineRef | null;
  seat: string;
  cabin_class: CabinClass | "";
  notes: string;
};

export function initialLeg(trip: TripDetailOut, leg?: LegOut): LegValues {
  const previous = trip.legs[trip.legs.length - 1];
  const zone = browserZone();
  return {
    mode: (leg?.mode as TravelMode | undefined) ?? (previous?.mode as TravelMode) ?? "drive",
    // A new leg starts where the last one ended.
    origin_stop_id: String(
      leg ? (leg.origin_stop_id ?? "") : (previous?.destination_stop_id ?? ""),
    ),
    destination_stop_id: String(leg?.destination_stop_id ?? ""),
    origin_label: leg?.origin_label ?? "",
    destination_label: leg?.destination_label ?? "",
    start: leg?.start_utc ? utcToZoned(leg.start_utc, leg.start_tz || zone) : "",
    start_tz: leg?.start_tz || previous?.end_tz || zone,
    end: leg?.end_utc ? utcToZoned(leg.end_utc, leg.end_tz || zone) : "",
    end_tz: leg?.end_tz || previous?.end_tz || zone,
    flight_number: leg?.flight_number ?? "",
    origin_airport: leg?.origin_airport ?? null,
    destination_airport: leg?.destination_airport ?? null,
    airline: leg?.airline ?? null,
    seat: leg?.seat ?? "",
    cabin_class: (leg?.cabin_class as CabinClass | "" | undefined) ?? "",
    notes: leg?.notes ?? "",
  };
}

export function validateLeg(v: LegValues): Record<string, string> {
  const errors: Record<string, string> = {};
  if (v.start && !isValidZone(v.start_tz)) errors.start_tz = "Unknown time zone.";
  if (v.end && !isValidZone(v.end_tz)) errors.end_tz = "Unknown time zone.";
  if (!errors.start_tz && !errors.end_tz && v.start && v.end) {
    if (zonedToUtc(v.end, v.end_tz) < zonedToUtc(v.start, v.start_tz))
      errors.end_utc = "The leg ends before it starts.";
  }
  return errors;
}

export function toLegPayload(v: LegValues): LegIn {
  const flight = v.mode === "flight";
  return {
    mode: v.mode,
    origin_stop_id: v.origin_stop_id ? Number(v.origin_stop_id) : null,
    destination_stop_id: v.destination_stop_id ? Number(v.destination_stop_id) : null,
    origin_label: v.origin_label.trim(),
    destination_label: v.destination_label.trim(),
    start_utc: v.start ? zonedToUtc(v.start, v.start_tz) : null,
    start_tz: v.start ? v.start_tz : "",
    end_utc: v.end ? zonedToUtc(v.end, v.end_tz) : null,
    end_tz: v.end ? v.end_tz : "",
    flight_number: flight ? v.flight_number.trim() : "",
    origin_airport_id: flight ? (v.origin_airport?.id ?? null) : null,
    destination_airport_id: flight ? (v.destination_airport?.id ?? null) : null,
    airline_id: flight ? (v.airline?.id ?? null) : null,
    seat: flight ? v.seat.trim() : "",
    cabin_class: flight && v.cabin_class ? v.cabin_class : null,
    // TODO(item 23, T21): a vehicle picker once `GET /vehicles` exists (vehicle_id).
    notes: v.notes,
  };
}

/** The trip's legs in order: add, edit, delete, move up/down (saved as a whole new order),
 * and each leg's route view (the routing editor's slot, items 25-26). Core editors only. */
export function LegsEditor({ trip }: { trip: TripDetailOut }) {
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [people, setPeople] = useState<number | null>(null);
  const invalidate = useInvalidateTrip();
  const remove = useDeleteLeg();
  const reorder = useReorderLegs();

  const move = (index: number, delta: -1 | 1) => {
    const ids = trip.legs.map((g) => g.id);
    const [moved] = ids.splice(index, 1);
    if (moved === undefined) return;
    ids.splice(index + delta, 0, moved);
    reorder.mutate(
      { tripId: trip.id, data: { leg_ids: ids } },
      { onSuccess: () => invalidate(trip.id) },
    );
  };

  return (
    <Section
      title="Legs"
      actions={
        editing === null && (
          <Button onClick={() => setEditing("new")} aria-label="Add leg">
            + Leg
          </Button>
        )
      }
    >
      <ol className="space-y-1">
        {trip.legs.map((leg, index) => {
          if (editing === leg.id) {
            return (
              <li key={leg.id}>
                <LegForm trip={trip} leg={leg} onDone={() => setEditing(null)} />
              </li>
            );
          }
          const [from, to] = legEnds(leg, trip.stops);
          const name = `${MODE_LABELS[leg.mode as TravelMode] ?? leg.mode} ${from} to ${to}`;
          return (
            <li key={leg.id} className="flex items-start justify-between gap-2 text-sm">
              <span>
                <span className="text-slate-500">{index + 1}.</span>{" "}
                <span className="font-medium">{MODE_LABELS[leg.mode as TravelMode]}</span> {from} →{" "}
                {to}
                {leg.notes && (
                  <span className="block whitespace-pre-wrap text-xs text-slate-600">
                    {leg.notes}
                  </span>
                )}
                {people === leg.id && <LegPeople trip={trip} leg={leg} />}
              </span>
              {editing === null && (
                <span className="flex shrink-0 items-center gap-2">
                  <Button
                    variant="link"
                    aria-label={`Move ${name} up`}
                    disabled={index === 0 || reorder.isPending}
                    onClick={() => move(index, -1)}
                  >
                    ↑
                  </Button>
                  <Button
                    variant="link"
                    aria-label={`Move ${name} down`}
                    disabled={index === trip.legs.length - 1 || reorder.isPending}
                    onClick={() => move(index, 1)}
                  >
                    ↓
                  </Button>
                  <Link
                    to={paths.legRoute(trip.id, leg.id)}
                    className="text-sm text-blue-700 hover:underline"
                  >
                    Route
                  </Link>
                  <Button
                    variant="link"
                    aria-label={`People on ${name}`}
                    onClick={() => setPeople(people === leg.id ? null : leg.id)}
                  >
                    People
                  </Button>
                  {leg.can_edit && (
                    <Button variant="link" onClick={() => setEditing(leg.id)}>
                      Edit
                    </Button>
                  )}
                  {leg.can_delete && (
                    <Button
                      variant="link"
                      aria-label={`Delete ${name}`}
                      onClick={() =>
                        remove.mutate({ legId: leg.id }, { onSuccess: () => invalidate(trip.id) })
                      }
                    >
                      Delete
                    </Button>
                  )}
                </span>
              )}
            </li>
          );
        })}
      </ol>
      {trip.legs.length === 0 && editing === null && (
        <p className="text-sm text-slate-600">
          Add how you got from place to place. Add stops first to connect legs to them on the map.
        </p>
      )}
      <MutationError error={remove.error ?? reorder.error} what="leg" />
      {editing === "new" && <LegForm trip={trip} onDone={() => setEditing(null)} />}
    </Section>
  );
}

/** Add or edit one leg. Core editors use it on the edit page; participants who may contribute
 * use it on the trip page for their own legs (the API makes those `participant_scope: author`). */
export function LegForm({
  trip,
  leg,
  onDone,
}: {
  trip: TripDetailOut;
  leg?: LegOut;
  onDone: () => void;
}) {
  const [values, setValues] = useState(() => initialLeg(trip, leg));
  const [shown, setShown] = useState<Record<string, string>>({});
  const invalidate = useInvalidateTrip();
  const create = useCreateLeg();
  const update = useUpdateLeg();
  const mutation = leg ? update : create;
  const errors = { ...fieldErrors(mutation.error), ...shown };
  const set = (change: Partial<LegValues>) => setValues((v) => ({ ...v, ...change }));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const problems = validateLeg(values);
    setShown(problems);
    if (Object.keys(problems).length) return;
    const done = {
      onSuccess: async () => {
        await invalidate(trip.id);
        onDone();
      },
    };
    if (leg) update.mutate({ legId: leg.id, data: toLegPayload(values) }, done);
    else create.mutate({ tripId: trip.id, data: toLegPayload(values) }, done);
  };

  const stopSelect = (key: "origin_stop_id" | "destination_stop_id", text: string) => (
    <Field label={text} htmlFor={`leg-${key}`} error={errors[key]}>
      <select
        id={`leg-${key}`}
        className={inputClass}
        value={values[key]}
        onChange={(e) => set({ [key]: e.target.value })}
      >
        <option value="">No stop</option>
        {trip.stops.map((s) => (
          <option key={s.id} value={s.id}>
            {stopName(trip.stops, s.id)}
          </option>
        ))}
      </select>
    </Field>
  );

  return (
    <form
      onSubmit={submit}
      noValidate
      aria-label={leg ? "Edit leg" : "New leg"}
      className="my-2 rounded border bg-slate-50 p-3"
    >
      <Field label="Mode" htmlFor="leg-mode" error={errors.mode}>
        <select
          id="leg-mode"
          className={inputClass}
          value={values.mode}
          onChange={(e) => set({ mode: e.target.value as TravelMode })}
        >
          {MODES.map((m) => (
            <option key={m} value={m}>
              {MODE_LABELS[m]}
            </option>
          ))}
        </select>
      </Field>
      <div className="grid grid-cols-2 gap-3">
        {stopSelect("origin_stop_id", "From stop")}
        {stopSelect("destination_stop_id", "To stop")}
      </div>
      {values.mode === "flight" && (
        <div className="mb-3 grid grid-cols-2 gap-3">
          <div>
            <span className="mb-0.5 block text-sm font-medium text-slate-700">From airport</span>
            <AirportSearch
              label="From airport"
              onSelect={(a) =>
                set({
                  origin_airport: {
                    id: a.id,
                    name: a.name,
                    code: a.iata_code || a.icao_code || a.ident,
                  },
                  origin_label: airportLabel(a),
                })
              }
            />
            <Chosen
              text={
                values.origin_airport &&
                `${values.origin_airport.code} ${values.origin_airport.name}`
              }
              what="origin airport"
              onClear={() => set({ origin_airport: null })}
            />
          </div>
          <div>
            <span className="mb-0.5 block text-sm font-medium text-slate-700">To airport</span>
            <AirportSearch
              label="To airport"
              onSelect={(a) =>
                set({
                  destination_airport: {
                    id: a.id,
                    name: a.name,
                    code: a.iata_code || a.icao_code || a.ident,
                  },
                  destination_label: airportLabel(a),
                })
              }
            />
            <Chosen
              text={
                values.destination_airport &&
                `${values.destination_airport.code} ${values.destination_airport.name}`
              }
              what="destination airport"
              onClear={() => set({ destination_airport: null })}
            />
          </div>
        </div>
      )}
      <div className="grid grid-cols-2 gap-3">
        <Field label="From (label)" htmlFor="leg-origin-label" error={errors.origin_label}>
          <input
            id="leg-origin-label"
            className={inputClass}
            maxLength={200}
            value={values.origin_label}
            placeholder={stopName(trip.stops, Number(values.origin_stop_id)) || "e.g. Home"}
            onChange={(e) => set({ origin_label: e.target.value })}
          />
        </Field>
        <Field label="To (label)" htmlFor="leg-destination-label" error={errors.destination_label}>
          <input
            id="leg-destination-label"
            className={inputClass}
            maxLength={200}
            value={values.destination_label}
            placeholder={stopName(trip.stops, Number(values.destination_stop_id))}
            onChange={(e) => set({ destination_label: e.target.value })}
          />
        </Field>
      </div>
      {values.mode === "flight" && (
        <>
          <div className="mb-3">
            <span className="mb-0.5 block text-sm font-medium text-slate-700">Airline</span>
            <AirlineSearch
              label="Airline"
              onSelect={(a) => set({ airline: { id: a.id, name: a.name, code: a.iata || a.icao } })}
            />
            <Chosen
              text={values.airline && airlineLabel(values.airline)}
              what="airline"
              onClear={() => set({ airline: null })}
            />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <Field label="Flight number" htmlFor="leg-flight-number" error={errors.flight_number}>
              <input
                id="leg-flight-number"
                className={inputClass}
                maxLength={16}
                value={values.flight_number}
                onChange={(e) => set({ flight_number: e.target.value })}
              />
            </Field>
            <Field label="Seat" htmlFor="leg-seat" error={errors.seat}>
              <input
                id="leg-seat"
                className={inputClass}
                maxLength={8}
                value={values.seat}
                onChange={(e) => set({ seat: e.target.value })}
              />
            </Field>
            <Field label="Cabin" htmlFor="leg-cabin" error={errors.cabin_class}>
              <select
                id="leg-cabin"
                className={inputClass}
                value={values.cabin_class}
                onChange={(e) => set({ cabin_class: e.target.value as CabinClass | "" })}
              >
                <option value="">Not recorded</option>
                {(Object.keys(CABIN_LABELS) as CabinClass[]).map((c) => (
                  <option key={c} value={c}>
                    {CABIN_LABELS[c]}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        </>
      )}
      <div className="mb-3 grid gap-2">
        <ZonedTimeInput
          label="Departed"
          local={values.start}
          zone={values.start_tz}
          error={errors.start_utc ?? errors.start_tz}
          onChange={(start, start_tz) => set({ start, start_tz })}
        />
        <ZonedTimeInput
          label="Arrived"
          local={values.end}
          zone={values.end_tz}
          error={errors.end_utc ?? errors.end_tz}
          onChange={(end, end_tz) => set({ end, end_tz })}
        />
      </div>
      <Field label="Leg notes" htmlFor="leg-notes" error={errors.notes}>
        <textarea
          id="leg-notes"
          className={inputClass}
          rows={2}
          maxLength={20000}
          value={values.notes}
          onChange={(e) => set({ notes: e.target.value })}
        />
      </Field>
      <MutationError
        error={Object.keys(fieldErrors(mutation.error)).length ? null : mutation.error}
        what="leg"
      />
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={mutation.isPending}>
          {leg ? "Save leg" : "Add leg"}
        </Button>
        <Button onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}

/** What a search picked, with a way to clear it. */
function Chosen({
  text,
  what,
  onClear,
}: {
  text: string | null | false;
  what: string;
  onClear: () => void;
}) {
  if (!text) return null;
  return (
    <p className="mt-0.5 flex items-center gap-1 text-xs text-slate-600">
      {text}
      <button
        type="button"
        className="text-slate-500 hover:text-red-700"
        aria-label={`Clear ${what}`}
        onClick={onClear}
      >
        ×
      </button>
    </p>
  );
}
