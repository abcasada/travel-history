import { type FormEvent, useState } from "react";
import { fieldErrors } from "../api/errors";
import {
  type TripDetailOut,
  type TripIn,
  useCreateTrip,
  useListPurposes,
  useUpdateTrip,
  type Visibility,
} from "../api/generated";
import { Button, Field, inputClass } from "../ui/form";
import { MutationError } from "../ui/QueryState";
import { useInvalidateTrip } from "./cache";
import { EDITABLE_VISIBILITIES, VISIBILITY_LABELS } from "./labels";

type Values = {
  title: string;
  start_date: string;
  end_date: string;
  purpose_id: string;
  /** "" on create: the purpose's default visibility (the server decides). */
  visibility: Visibility | "";
  notes: string;
};

export function initialValues(trip?: TripDetailOut): Values {
  return {
    title: trip?.title ?? "",
    start_date: trip?.start_date ?? "",
    end_date: trip?.end_date ?? "",
    purpose_id: trip?.purpose ? String(trip.purpose.id) : "",
    visibility: (trip?.visibility as Visibility | undefined) ?? "",
    notes: trip?.notes ?? "",
  };
}

/** Client-side checks; the server checks again and its 422 field errors are shown the same way. */
export function validate(v: Values): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!v.title.trim()) errors.title = "Give the trip a title.";
  if (!v.start_date) errors.start_date = "When did it start?";
  if (!v.end_date) errors.end_date = "When did it end?";
  if (v.start_date && v.end_date && v.end_date < v.start_date)
    errors.end_date = "The end can't be before the start.";
  return errors;
}

function toPayload(v: Values): TripIn {
  return {
    title: v.title.trim(),
    start_date: v.start_date,
    end_date: v.end_date,
    purpose_id: v.purpose_id ? Number(v.purpose_id) : null,
    ...(v.visibility ? { visibility: v.visibility } : {}),
    notes: v.notes,
  };
}

/**
 * The trip's own fields, for creating (no `trip`) or editing one. Calls `onSaved` with the
 * saved trip. The pattern every editor follows: local state, `validate`, the generated
 * mutation hook, server field errors merged under the client ones, then invalidate.
 */
export function TripFieldsForm({
  trip,
  onSaved,
  onCancel,
}: {
  trip?: TripDetailOut;
  onSaved: (trip: TripDetailOut) => void;
  onCancel?: () => void;
}) {
  const [values, setValues] = useState<Values>(() => initialValues(trip));
  const [shown, setShown] = useState<Record<string, string>>({});
  const purposes = useListPurposes();
  const invalidate = useInvalidateTrip();
  const create = useCreateTrip();
  const update = useUpdateTrip();
  const mutation = trip ? update : create;
  const errors = { ...fieldErrors(mutation.error), ...shown };
  const set = (change: Partial<Values>) => setValues((v) => ({ ...v, ...change }));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const problems = validate(values);
    setShown(problems);
    if (Object.keys(problems).length) return;
    const done = {
      onSuccess: async (saved: TripDetailOut) => {
        await invalidate(saved.id);
        onSaved(saved);
      },
    };
    if (trip) update.mutate({ tripId: trip.id, data: toPayload(values) }, done);
    else create.mutate({ data: toPayload(values) }, done);
  };

  return (
    <form onSubmit={submit} noValidate aria-label={trip ? "Trip details" : "New trip"}>
      <Field label="Title" htmlFor="trip-title" error={errors.title}>
        <input
          id="trip-title"
          className={inputClass}
          value={values.title}
          maxLength={200}
          onChange={(e) => set({ title: e.target.value })}
        />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Start date" htmlFor="trip-start" error={errors.start_date}>
          <input
            id="trip-start"
            type="date"
            className={inputClass}
            value={values.start_date}
            onChange={(e) =>
              set({
                start_date: e.target.value,
                end_date: values.end_date || e.target.value,
              })
            }
          />
        </Field>
        <Field label="End date" htmlFor="trip-end" error={errors.end_date}>
          <input
            id="trip-end"
            type="date"
            className={inputClass}
            value={values.end_date}
            min={values.start_date || undefined}
            onChange={(e) => set({ end_date: e.target.value })}
          />
        </Field>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Purpose" htmlFor="trip-purpose" error={errors.purpose_id}>
          <select
            id="trip-purpose"
            className={inputClass}
            value={values.purpose_id}
            onChange={(e) => set({ purpose_id: e.target.value })}
          >
            <option value="">None</option>
            {purposes.data
              ?.filter((p) => !p.archived || String(p.id) === values.purpose_id)
              .map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
          </select>
        </Field>
        <Field label="Who can see it" htmlFor="trip-visibility" error={errors.visibility}>
          <select
            id="trip-visibility"
            className={inputClass}
            value={values.visibility}
            onChange={(e) => set({ visibility: e.target.value as Visibility | "" })}
          >
            {!trip && <option value="">Default for the purpose</option>}
            {EDITABLE_VISIBILITIES.concat(values.visibility === "public" ? ["public"] : []).map(
              (v) => (
                <option key={v} value={v}>
                  {VISIBILITY_LABELS[v]}
                </option>
              ),
            )}
          </select>
        </Field>
      </div>
      <Field label="Notes" htmlFor="trip-notes" error={errors.notes}>
        <textarea
          id="trip-notes"
          className={inputClass}
          rows={3}
          value={values.notes}
          onChange={(e) => set({ notes: e.target.value })}
        />
      </Field>
      <MutationError
        error={Object.keys(fieldErrors(mutation.error)).length ? null : mutation.error}
        what="trip"
      />
      <div className="mt-2 flex gap-2">
        <Button type="submit" variant="primary" disabled={mutation.isPending}>
          {trip ? "Save" : "Create trip"}
        </Button>
        {onCancel && <Button onClick={onCancel}>Cancel</Button>}
      </div>
    </form>
  );
}
