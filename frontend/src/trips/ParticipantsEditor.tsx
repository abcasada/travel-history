import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import {
  getGetMeQueryKey,
  getListPersonsQueryKey,
  type TripDetailOut,
  useAddParticipant,
  useCreateMyPerson,
  useCreatePerson,
  useListPersons,
  useRemoveParticipant,
} from "../api/generated";
import { useMe } from "../auth/AuthGate";
import { Button, inputClass, Section } from "../ui/form";
import { MutationError } from "../ui/QueryState";
import { useInvalidateTrip } from "./cache";

/**
 * Who went: the trip-level participants. Add anyone you can see, yourself (which first creates
 * your traveller profile if your account has none), or a new person (e.g. a child without an
 * account). Per-leg participation is item 21.
 */
export function ParticipantsEditor({ trip }: { trip: TripDetailOut }) {
  const me = useMe();
  const client = useQueryClient();
  const invalidate = useInvalidateTrip();
  const persons = useListPersons();
  const add = useAddParticipant();
  const remove = useRemoveParticipant();
  const createPerson = useCreatePerson();
  const createMine = useCreateMyPerson();
  const [chosen, setChosen] = useState("");
  const [newName, setNewName] = useState("");

  const onTrip = new Set(trip.participants.filter((p) => p.on_trip).map((p) => p.person.id));
  const candidates = (persons.data ?? []).filter((p) => !onTrip.has(p.id));
  const meOnTrip = me.person_id !== null && onTrip.has(me.person_id);
  const busy = add.isPending || createPerson.isPending || createMine.isPending;

  const addPerson = (personId: number) =>
    add.mutateAsync({ tripId: trip.id, data: { person_id: personId } }).then(async () => {
      await invalidate(trip.id);
      setChosen("");
    });

  const addMe = async () => {
    let personId = me.person_id;
    if (personId === null) {
      personId = (await createMine.mutateAsync()).person_id ?? null;
      await client.invalidateQueries({ queryKey: getGetMeQueryKey() });
      await client.invalidateQueries({ queryKey: getListPersonsQueryKey() });
    }
    if (personId !== null) await addPerson(personId);
  };

  const addNew = async (event: FormEvent) => {
    event.preventDefault();
    const name = newName.trim();
    if (!name) return;
    const person = await createPerson.mutateAsync({ data: { display_name: name } });
    await client.invalidateQueries({ queryKey: getListPersonsQueryKey() });
    setNewName("");
    await addPerson(person.id);
  };

  // mutateAsync rejects on failure; the error is shown from the mutation's state.
  const quietly = (run: () => Promise<unknown>) => () => void run().catch(() => {});

  return (
    <Section title="Who went">
      <ul className="mb-2 flex flex-wrap gap-2 text-sm">
        {trip.participants.map((p) => (
          <li
            key={p.person.id}
            className="flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5"
          >
            {p.person.display_name}
            {!p.on_trip && <span className="text-slate-500">(some legs)</span>}
            {p.on_trip && (
              <button
                type="button"
                className="text-slate-500 hover:text-red-700"
                aria-label={`Remove ${p.person.display_name}`}
                disabled={remove.isPending}
                onClick={() =>
                  remove.mutate(
                    { tripId: trip.id, personId: p.person.id },
                    { onSuccess: () => invalidate(trip.id) },
                  )
                }
              >
                ×
              </button>
            )}
          </li>
        ))}
        {trip.participants.length === 0 && <li className="text-slate-600">Nobody yet.</li>}
      </ul>
      <div className="flex flex-wrap items-center gap-2">
        {!meOnTrip && me.role !== "viewer" && (
          <Button onClick={quietly(addMe)} disabled={busy}>
            Add me
          </Button>
        )}
        <select
          aria-label="Person to add"
          className={`${inputClass} max-w-48`}
          value={chosen}
          onChange={(e) => setChosen(e.target.value)}
        >
          <option value="">Choose a person…</option>
          {candidates.map((p) => (
            <option key={p.id} value={p.id}>
              {p.display_name}
              {p.is_me ? " (me)" : ""}
            </option>
          ))}
        </select>
        <Button onClick={quietly(() => addPerson(Number(chosen)))} disabled={!chosen || busy}>
          Add
        </Button>
      </div>
      <form onSubmit={(e) => void addNew(e).catch(() => {})} className="mt-2 flex gap-2">
        <input
          aria-label="New person's name"
          placeholder="Someone new (e.g. a child without an account)"
          className={`${inputClass} max-w-72`}
          maxLength={150}
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
        />
        <Button type="submit" disabled={!newName.trim() || busy}>
          Add new person
        </Button>
      </form>
      <MutationError
        error={add.error ?? remove.error ?? createPerson.error ?? createMine.error}
        what="participant"
      />
    </Section>
  );
}
