import { type FormEvent, useState } from "react";
import { fieldErrors } from "../api/errors";
import {
  type StopKind,
  type StopOut,
  type TripDetailOut,
  useCreateStop,
  useDeleteStop,
  useUpdateStop,
} from "../api/generated";
import { browserZone, isValidZone, utcToZoned, zonedToUtc } from "../lib/time";
import type { LngLat } from "../map/store";
import { Button, Field, inputClass, Section } from "../ui/form";
import { MutationError } from "../ui/QueryState";
import { useInvalidateTrip } from "./cache";
import { PlaceInput, ZonedTimeInput } from "./inputs";
import { label, STOP_KIND_LABELS, STOP_KINDS } from "./labels";

type StopValues = {
  kind: StopKind;
  name: string;
  point: LngLat | null;
  arrive: string;
  depart: string;
  tz: string;
};

function initial(stop?: StopOut): StopValues {
  const tz = stop?.tz || browserZone();
  return {
    kind: (stop?.kind as StopKind | undefined) ?? "destination",
    name: stop?.place.name ?? "",
    point: stop ? { lon: stop.place.lon, lat: stop.place.lat } : null,
    arrive: stop?.arrive_utc ? utcToZoned(stop.arrive_utc, tz) : "",
    depart: stop?.depart_utc ? utcToZoned(stop.depart_utc, tz) : "",
    tz,
  };
}

export function validateStop(v: StopValues): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!v.point) errors.place = "Set where the stop is.";
  if ((v.arrive || v.depart) && !isValidZone(v.tz)) errors.tz = "Unknown time zone.";
  if (v.arrive && v.depart && v.depart < v.arrive) errors.depart = "Leaving before arriving?";
  return errors;
}

const toUtc = (local: string, tz: string) => (local ? zonedToUtc(local, tz) : null);

/** The trip's stops (places along the way): list, add, edit, delete. Core editors only. */
export function StopsEditor({ trip }: { trip: TripDetailOut }) {
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const invalidate = useInvalidateTrip();
  const remove = useDeleteStop();
  return (
    <Section
      title="Stops"
      actions={
        editing === null && (
          <Button onClick={() => setEditing("new")} aria-label="Add stop">
            + Stop
          </Button>
        )
      }
    >
      <ul className="space-y-1">
        {trip.stops.map((stop) =>
          editing === stop.id ? (
            <li key={stop.id}>
              <StopForm trip={trip} stop={stop} onDone={() => setEditing(null)} />
            </li>
          ) : (
            <li key={stop.id} className="flex items-center justify-between gap-2 text-sm">
              <span>
                <span className="font-medium">{stop.place.name || "Unnamed place"}</span>{" "}
                <span className="text-slate-500">{label(STOP_KIND_LABELS, stop.kind)}</span>
              </span>
              {stop.can_edit && editing === null && (
                <span className="flex gap-2">
                  <Button variant="link" onClick={() => setEditing(stop.id)}>
                    Edit
                  </Button>
                  <Button
                    variant="link"
                    aria-label={`Delete stop ${stop.place.name}`}
                    onClick={() =>
                      remove.mutate({ stopId: stop.id }, { onSuccess: () => invalidate(trip.id) })
                    }
                  >
                    Delete
                  </Button>
                </span>
              )}
            </li>
          ),
        )}
      </ul>
      {trip.stops.length === 0 && editing === null && (
        <p className="text-sm text-slate-600">
          Add the places you went: where you stayed, visited or passed through.
        </p>
      )}
      <MutationError error={remove.error} what="stop" />
      {editing === "new" && <StopForm trip={trip} onDone={() => setEditing(null)} />}
    </Section>
  );
}

function StopForm({
  trip,
  stop,
  onDone,
}: {
  trip: TripDetailOut;
  stop?: StopOut;
  onDone: () => void;
}) {
  const [values, setValues] = useState(() => initial(stop));
  const [shown, setShown] = useState<Record<string, string>>({});
  const invalidate = useInvalidateTrip();
  const create = useCreateStop();
  const update = useUpdateStop();
  const mutation = stop ? update : create;
  const errors = { ...fieldErrors(mutation.error), ...shown };
  const set = (change: Partial<StopValues>) => setValues((v) => ({ ...v, ...change }));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const problems = validateStop(values);
    setShown(problems);
    if (Object.keys(problems).length || !values.point) return;
    const times = {
      arrive_utc: toUtc(values.arrive, values.tz),
      depart_utc: toUtc(values.depart, values.tz),
      tz: values.tz,
    };
    const place = { name: values.name.trim(), lon: values.point.lon, lat: values.point.lat };
    const done = {
      onSuccess: async () => {
        await invalidate(trip.id);
        onDone();
      },
    };
    if (stop) {
      // A place belongs to whoever created it; a changed name or point is a new place.
      const moved =
        place.name !== stop.place.name ||
        place.lon !== stop.place.lon ||
        place.lat !== stop.place.lat;
      update.mutate(
        { stopId: stop.id, data: { kind: values.kind, ...times, ...(moved ? { place } : {}) } },
        done,
      );
    } else {
      create.mutate({ tripId: trip.id, data: { kind: values.kind, ...times, place } }, done);
    }
  };

  const pickLabel = stop ? `the stop "${stop.place.name || "unnamed"}"` : "the new stop";
  return (
    <form
      onSubmit={submit}
      noValidate
      aria-label={stop ? "Edit stop" : "New stop"}
      className="my-2 rounded border bg-slate-50 p-3"
    >
      <div className="grid grid-cols-2 gap-3">
        <Field label="Place name" htmlFor="stop-name" error={errors.name}>
          <input
            id="stop-name"
            className={inputClass}
            value={values.name}
            maxLength={200}
            onChange={(e) => set({ name: e.target.value })}
          />
        </Field>
        <Field label="Kind" htmlFor="stop-kind" error={errors.kind}>
          <select
            id="stop-kind"
            className={inputClass}
            value={values.kind}
            onChange={(e) => set({ kind: e.target.value as StopKind })}
          >
            {STOP_KINDS.map((k) => (
              <option key={k} value={k}>
                {STOP_KIND_LABELS[k]}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <div className="mb-3">
        <span className="mb-0.5 block text-sm font-medium text-slate-700">Location</span>
        <PlaceInput
          value={values.point}
          pickLabel={pickLabel}
          error={errors.place ?? errors.lon ?? errors.lat}
          onChange={(point, name) => set({ point, ...(name && !values.name ? { name } : {}) })}
        />
      </div>
      <div className="mb-3 grid gap-2">
        <ZonedTimeInput
          label="Arrived"
          local={values.arrive}
          zone={values.tz}
          error={errors.arrive_utc ?? errors.tz}
          onChange={(arrive, tz) => set({ arrive, tz })}
        />
        <ZonedTimeInput
          label="Left"
          local={values.depart}
          zone={values.tz}
          error={errors.depart ?? errors.depart_utc}
          onChange={(depart, tz) => set({ depart, tz })}
        />
      </div>
      <MutationError
        error={Object.keys(fieldErrors(mutation.error)).length ? null : mutation.error}
        what="stop"
      />
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={mutation.isPending}>
          {stop ? "Save stop" : "Add stop"}
        </Button>
        <Button onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}
