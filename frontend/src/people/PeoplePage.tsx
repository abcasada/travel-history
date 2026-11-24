import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { fieldErrors } from "../api/errors";
import {
  getGetMeQueryKey,
  getListPersonsQueryKey,
  type PersonOut,
  type PersonVisibility,
  useListPersons,
  useUpdatePerson,
} from "../api/generated";
import { invalidateTrip } from "../trips/cache";
import { Button, inputClass } from "../ui/form";
import { MutationError, QueryState } from "../ui/QueryState";

export const PERSON_VISIBILITY_LABELS: Record<PersonVisibility, string> = {
  family: "Family (everyone can add them to trips)",
  private: "Private (only you, and trips they're on)",
};

export function validatePerson(name: string): Record<string, string> {
  return name.trim() ? {} : { display_name: "A person needs a name." };
}

/** `/people`: the people you may change (yourself, people you added such as children; the
 * Admin may rename anyone). Others are listed read-only so names are easy to check. */
export function PeoplePage() {
  const persons = useListPersons();
  return (
    <div className="p-4">
      <h2 className="mb-1 text-lg font-semibold">People</h2>
      <p className="mb-3 text-sm text-slate-600">
        Travellers on trips, with or without an account. Rename the people you manage or choose who
        can see them.
      </p>
      <QueryState query={persons} what="people">
        {(rows) => {
          const editable = rows.filter((p) => p.can_edit);
          const others = rows.filter((p) => !p.can_edit);
          return (
            <>
              {editable.length === 0 ? (
                <p className="mb-3 text-sm text-slate-600">There's nobody you can change.</p>
              ) : (
                <ul className="mb-4 space-y-2">
                  {editable.map((p) => (
                    <PersonRow key={p.id} person={p} />
                  ))}
                </ul>
              )}
              {others.length > 0 && (
                <>
                  <h3 className="mb-1 font-medium">Everyone else</h3>
                  <ul className="flex flex-wrap gap-2 text-sm">
                    {others.map((p) => (
                      <li key={p.id} className="rounded-full bg-slate-100 px-2 py-0.5">
                        {p.display_name}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </>
          );
        }}
      </QueryState>
    </div>
  );
}

function PersonRow({ person }: { person: PersonOut }) {
  const client = useQueryClient();
  const update = useUpdatePerson();
  const [name, setName] = useState<string | null>(null);
  const [shown, setShown] = useState<Record<string, string>>({});
  const errors = { ...fieldErrors(update.error), ...shown };
  // Names show on trips and in the participant pickers; "me" carries the person link.
  const refresh = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: getListPersonsQueryKey() }),
      client.invalidateQueries({ queryKey: getGetMeQueryKey() }),
      invalidateTrip(client),
    ]);

  const rename = (event: FormEvent) => {
    event.preventDefault();
    if (name === null) return;
    const problems = validatePerson(name);
    setShown(problems);
    if (Object.keys(problems).length) return;
    update.mutate(
      { personId: person.id, data: { display_name: name.trim() } },
      {
        onSuccess: async () => {
          await refresh();
          setName(null);
        },
      },
    );
  };

  return (
    <li className="flex flex-wrap items-center gap-2 text-sm">
      {name === null ? (
        <span className="min-w-32 font-medium">
          {person.display_name}
          {person.is_me && <span className="text-slate-500"> (me)</span>}
          {!person.manages && <span className="text-slate-500"> (has an account)</span>}
        </span>
      ) : (
        <form
          onSubmit={rename}
          noValidate
          aria-label={`Rename ${person.display_name}`}
          className="flex flex-wrap items-start gap-1"
        >
          <div>
            <input
              aria-label="Name"
              className={`${inputClass} max-w-48`}
              maxLength={150}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            {errors.display_name && <p className="text-xs text-red-700">{errors.display_name}</p>}
          </div>
          <Button type="submit" variant="primary" disabled={update.isPending}>
            Save
          </Button>
          <Button onClick={() => setName(null)}>Cancel</Button>
        </form>
      )}
      <select
        aria-label={`Who sees ${person.display_name}`}
        className={`${inputClass} max-w-72`}
        value={person.visibility}
        disabled={update.isPending}
        onChange={(e) =>
          update.mutate(
            { personId: person.id, data: { visibility: e.target.value as PersonVisibility } },
            { onSuccess: () => refresh() },
          )
        }
      >
        {(Object.keys(PERSON_VISIBILITY_LABELS) as PersonVisibility[]).map((v) => (
          <option key={v} value={v}>
            {PERSON_VISIBILITY_LABELS[v]}
          </option>
        ))}
      </select>
      {name === null && (
        <Button
          variant="link"
          aria-label={`Rename ${person.display_name}`}
          onClick={() => setName(person.display_name)}
        >
          Rename
        </Button>
      )}
      <MutationError
        error={Object.keys(fieldErrors(update.error)).length ? null : update.error}
        what="person"
      />
    </li>
  );
}
