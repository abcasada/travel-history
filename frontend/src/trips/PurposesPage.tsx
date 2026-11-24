import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { fieldErrors } from "../api/errors";
import {
  getListPurposesQueryKey,
  type PurposeOut,
  type PurposeVisibility,
  useCreatePurpose,
  useListPurposes,
  useUpdatePurpose,
} from "../api/generated";
import { useMe } from "../auth/AuthGate";
import { Button, Field, inputClass } from "../ui/form";
import { MutationError, QueryState } from "../ui/QueryState";
import { invalidateTrip } from "./cache";
import { EDITABLE_VISIBILITIES, VISIBILITY_LABELS } from "./labels";

export function validatePurpose(name: string): Record<string, string> {
  return name.trim() ? {} : { name: "A purpose needs a name." };
}

/** `/purposes`: the caller's own trip purposes (seven are seeded). Each sets the visibility a
 * new trip starts with. Purposes are archived, never deleted, so old trips keep theirs; the
 * bulk bar's digit keys follow this order (archived ones take none). */
export function PurposesPage() {
  const me = useMe();
  const purposes = useListPurposes();
  if (me.role === "viewer") {
    return <p className="p-4 text-sm text-slate-600">Viewers don't have trip purposes.</p>;
  }
  return (
    <div className="p-4">
      <h2 className="mb-1 text-lg font-semibold">My purposes</h2>
      <p className="mb-3 text-sm text-slate-600">
        Why you travelled. A new trip takes its purpose's visibility unless you choose another.
      </p>
      <QueryState query={purposes} what="purposes">
        {(rows) => (
          <ol className="mb-4 space-y-1">
            {rows.map((p, index) => (
              <PurposeRow key={p.id} purpose={p} rows={rows} index={index} />
            ))}
          </ol>
        )}
      </QueryState>
      <NewPurpose />
    </div>
  );
}

function useRefresh() {
  const client = useQueryClient();
  // Purpose names show on trips and in the list filters.
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: getListPurposesQueryKey() }),
      invalidateTrip(client),
    ]);
}

function VisibilitySelect({
  id,
  value,
  onChange,
}: {
  id: string;
  value: string;
  onChange: (v: PurposeVisibility) => void;
}) {
  // Public isn't offered: nothing renders public trips before T37 (D-109).
  return (
    <select
      id={id}
      aria-label="Default visibility"
      className={`${inputClass} max-w-44`}
      value={value}
      onChange={(e) => onChange(e.target.value as PurposeVisibility)}
    >
      {EDITABLE_VISIBILITIES.map((v) => (
        <option key={v} value={v}>
          {VISIBILITY_LABELS[v]}
        </option>
      ))}
    </select>
  );
}

function PurposeRow({
  purpose,
  rows,
  index,
}: {
  purpose: PurposeOut;
  rows: PurposeOut[];
  index: number;
}) {
  const refresh = useRefresh();
  const update = useUpdatePurpose();
  const [name, setName] = useState<string | null>(null);

  const change = (data: Parameters<typeof update.mutate>[0]["data"]) =>
    update.mutate({ purposeId: purpose.id, data }, { onSuccess: () => refresh() });

  // Number the whole list 0..n-1 in the new order; only rows whose number changes are sent.
  const move = (delta: -1 | 1) => {
    const order = [...rows];
    const [moved] = order.splice(index, 1);
    if (!moved) return;
    order.splice(index + delta, 0, moved);
    const changed = order.flatMap((row, sort) => (row.sort === sort ? [] : [{ row, sort }]));
    void (async () => {
      for (const { row, sort } of changed) {
        await update.mutateAsync({ purposeId: row.id, data: { sort } });
      }
      await refresh();
    })().catch(() => {}); // the error shows from the mutation's state
  };

  const rename = (event: FormEvent) => {
    event.preventDefault();
    if (name === null || validatePurpose(name).name) return;
    update.mutate(
      { purposeId: purpose.id, data: { name: name.trim() } },
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
        <span className={`min-w-32 font-medium ${purpose.archived ? "text-slate-400" : ""}`}>
          {purpose.name}
          {purpose.archived && " (archived)"}
        </span>
      ) : (
        <form onSubmit={rename} aria-label={`Rename ${purpose.name}`} className="flex gap-1">
          <input
            aria-label="Purpose name"
            className={`${inputClass} max-w-40`}
            maxLength={64}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Button type="submit" variant="primary" disabled={!name.trim() || update.isPending}>
            Save
          </Button>
          <Button onClick={() => setName(null)}>Cancel</Button>
        </form>
      )}
      <VisibilitySelect
        id={`purpose-${purpose.id}-visibility`}
        value={purpose.default_visibility}
        onChange={(v) => change({ default_visibility: v })}
      />
      <span className="flex gap-2">
        {name === null && (
          <Button
            variant="link"
            aria-label={`Rename ${purpose.name}`}
            onClick={() => setName(purpose.name)}
          >
            Rename
          </Button>
        )}
        <Button
          variant="link"
          aria-label={`Move ${purpose.name} up`}
          disabled={index === 0 || update.isPending}
          onClick={() => move(-1)}
        >
          ↑
        </Button>
        <Button
          variant="link"
          aria-label={`Move ${purpose.name} down`}
          disabled={index === rows.length - 1 || update.isPending}
          onClick={() => move(1)}
        >
          ↓
        </Button>
        <Button
          variant="link"
          aria-label={`${purpose.archived ? "Restore" : "Archive"} ${purpose.name}`}
          disabled={update.isPending}
          onClick={() => change({ archived: !purpose.archived })}
        >
          {purpose.archived ? "Restore" : "Archive"}
        </Button>
      </span>
      <MutationError error={update.error} what="purpose" />
    </li>
  );
}

function NewPurpose() {
  const refresh = useRefresh();
  const create = useCreatePurpose();
  const [name, setName] = useState("");
  const [visibility, setVisibility] = useState<PurposeVisibility>("participants");
  const [shown, setShown] = useState<Record<string, string>>({});
  const errors = { ...fieldErrors(create.error), ...shown };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const problems = validatePurpose(name);
    setShown(problems);
    if (Object.keys(problems).length) return;
    create.mutate(
      { data: { name: name.trim(), default_visibility: visibility } },
      {
        onSuccess: async () => {
          setName("");
          await refresh();
        },
      },
    );
  };

  return (
    <form onSubmit={submit} noValidate aria-label="New purpose" className="rounded border p-3">
      <Field label="New purpose" htmlFor="purpose-new-name" error={errors.name}>
        <input
          id="purpose-new-name"
          className={`${inputClass} max-w-64`}
          maxLength={64}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </Field>
      <div className="mb-3 flex items-center gap-2 text-sm">
        <label htmlFor="purpose-new-visibility">New trips are</label>
        <VisibilitySelect id="purpose-new-visibility" value={visibility} onChange={setVisibility} />
      </div>
      <MutationError
        error={Object.keys(fieldErrors(create.error)).length ? null : create.error}
        what="purpose"
      />
      <Button type="submit" variant="primary" disabled={create.isPending}>
        Add purpose
      </Button>
    </form>
  );
}
