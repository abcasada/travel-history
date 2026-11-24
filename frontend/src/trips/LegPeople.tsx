import { useState } from "react";
import {
  type LegOut,
  type TripDetailOut,
  useListPersons,
  useSetLegParticipation,
  useSetMyLegParticipation,
} from "../api/generated";
import { useMe } from "../auth/AuthGate";
import { Button, inputClass } from "../ui/form";
import { MutationError } from "../ui/QueryState";
import { useInvalidateTrip } from "./cache";

/** Who was on one leg, for core editors: tick the trip's people, or add someone only to this
 * leg (anyone the editor can see). The server keeps overrides per person and leg. */
export function LegPeople({ trip, leg }: { trip: TripDetailOut; leg: LegOut }) {
  const invalidate = useInvalidateTrip();
  const persons = useListPersons();
  const set = useSetLegParticipation();
  const [chosen, setChosen] = useState("");
  const known = new Set(trip.participants.map((p) => p.person.id));
  const others = (persons.data ?? []).filter((p) => !known.has(p.id));

  const change = (personId: number, onLeg: boolean) =>
    set.mutate(
      { legId: leg.id, personId, data: { on_leg: onLeg } },
      {
        onSuccess: async () => {
          setChosen("");
          await invalidate(trip.id);
        },
      },
    );

  return (
    <fieldset className="mt-1 rounded border bg-slate-50 p-2 text-sm">
      <legend className="px-1 text-xs text-slate-600">People on this leg</legend>
      <div className="flex flex-wrap gap-3">
        {trip.participants.map((p) => (
          <label key={p.person.id} className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={leg.participant_ids.includes(p.person.id)}
              disabled={set.isPending}
              onChange={(e) => change(p.person.id, e.target.checked)}
            />
            {p.person.display_name}
          </label>
        ))}
      </div>
      {others.length > 0 && (
        <div className="mt-2 flex gap-2">
          <select
            aria-label="Someone only on this leg"
            className={`${inputClass} max-w-48`}
            value={chosen}
            onChange={(e) => setChosen(e.target.value)}
          >
            <option value="">Someone else…</option>
            {others.map((p) => (
              <option key={p.id} value={p.id}>
                {p.display_name}
              </option>
            ))}
          </select>
          <Button onClick={() => change(Number(chosen), true)} disabled={!chosen || set.isPending}>
            Add to leg
          </Button>
        </div>
      )}
      <MutationError error={set.error} what="leg" />
    </fieldset>
  );
}

/** "I was on this leg": a participant's own override. Shown when the caller may contribute and
 * has a person (the API answers 409 without one). */
export function MyLegToggle({
  trip,
  leg,
  name,
}: {
  trip: TripDetailOut;
  leg: LegOut;
  name: string;
}) {
  const me = useMe();
  const invalidate = useInvalidateTrip();
  const set = useSetMyLegParticipation();
  if (me.person_id === null || !trip.access.contribute) return null;
  const on = leg.participant_ids.includes(me.person_id);
  return (
    <>
      <label className="mt-1 flex items-center gap-1 text-xs">
        <input
          type="checkbox"
          aria-label={`I was on ${name}`}
          checked={on}
          disabled={set.isPending}
          onChange={(e) =>
            set.mutate(
              { legId: leg.id, data: { on_leg: e.target.checked } },
              { onSuccess: () => invalidate(trip.id) },
            )
          }
        />
        I was on this leg
      </label>
      <MutationError error={set.error} what="leg" />
    </>
  );
}
