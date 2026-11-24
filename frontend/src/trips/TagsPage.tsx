import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { fieldErrors } from "../api/errors";
import { type TagOut, useDeleteTag, useListTags, useUpdateTag } from "../api/generated";
import { useMe } from "../auth/AuthGate";
import { Button, inputClass } from "../ui/form";
import { MutationError, QueryState } from "../ui/QueryState";
import { invalidateTrip } from "./cache";

const COLOR = /^#[0-9a-fA-F]{6}$/;

export function validateTag(name: string, color: string): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!name.trim()) errors.name = "A tag needs a name.";
  if (color && !COLOR.test(color)) errors.color = "Use a colour like #2563eb.";
  return errors;
}

/** `/tags`: the caller's own tag definitions. Tags are added from a trip page (or in bulk);
 * here they are renamed, coloured or deleted (deleting takes the tag off every trip). */
export function TagsPage() {
  const me = useMe();
  const tags = useListTags();
  return (
    <div className="p-4">
      <h2 className="mb-1 text-lg font-semibold">My tags</h2>
      <p className="mb-3 text-sm text-slate-600">
        Your own labels for trips. Other people's tags show only on the trips they tagged.
      </p>
      <QueryState query={tags} what="tags">
        {(rows) =>
          rows.length === 0 ? (
            <p className="text-sm text-slate-600">
              {me.role === "viewer"
                ? "Viewers don't tag trips."
                : "No tags yet. Add one from a trip's page."}
            </p>
          ) : (
            <ul className="space-y-2">
              {rows.map((tag) => (
                <TagRow key={tag.id} tag={tag} />
              ))}
            </ul>
          )
        }
      </QueryState>
    </div>
  );
}

function TagRow({ tag }: { tag: TagOut }) {
  const client = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(tag.name);
  const [color, setColor] = useState(tag.color);
  const [shown, setShown] = useState<Record<string, string>>({});
  const update = useUpdateTag();
  const remove = useDeleteTag();
  const errors = { ...fieldErrors(update.error), ...shown };
  // A tag's name shows on trips: refresh every trip view, not only this list.
  const refresh = () => invalidateTrip(client);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const problems = validateTag(name, color);
    setShown(problems);
    if (Object.keys(problems).length) return;
    update.mutate(
      { tagId: tag.id, data: { name: name.trim(), color } },
      {
        onSuccess: async () => {
          await refresh();
          setEditing(false);
        },
      },
    );
  };

  const onDelete = () => {
    const where = tag.trip_count === 1 ? "1 trip" : `${tag.trip_count} trips`;
    if (!window.confirm(`Delete #${tag.name}? It comes off ${where}.`)) return;
    remove.mutate({ tagId: tag.id }, { onSuccess: () => refresh() });
  };

  if (editing) {
    return (
      <li>
        <form
          onSubmit={submit}
          noValidate
          aria-label={`Edit tag ${tag.name}`}
          className="flex flex-wrap items-start gap-2 rounded border bg-slate-50 p-2"
        >
          <div>
            <input
              aria-label="Tag name"
              className={`${inputClass} max-w-48`}
              maxLength={64}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            {errors.name && <p className="text-xs text-red-700">{errors.name}</p>}
          </div>
          <div>
            <input
              aria-label="Colour"
              placeholder="#rrggbb"
              className={`${inputClass} max-w-28`}
              maxLength={7}
              value={color}
              onChange={(e) => setColor(e.target.value)}
            />
            {errors.color && <p className="text-xs text-red-700">{errors.color}</p>}
          </div>
          <Button type="submit" variant="primary" disabled={update.isPending}>
            Save
          </Button>
          <Button onClick={() => setEditing(false)}>Cancel</Button>
          <MutationError
            error={Object.keys(fieldErrors(update.error)).length ? null : update.error}
            what="tag"
          />
        </form>
      </li>
    );
  }
  return (
    <li className="flex items-center justify-between gap-2 text-sm">
      <span className="flex items-center gap-2">
        <span
          aria-hidden
          className="inline-block h-3 w-3 rounded-full border"
          style={{ background: tag.color || "transparent" }}
        />
        <span className="font-medium">#{tag.name}</span>
        <span className="text-slate-500">
          {tag.trip_count === 1 ? "1 trip" : `${tag.trip_count} trips`}
        </span>
      </span>
      <span className="flex gap-2">
        <Button variant="link" aria-label={`Edit #${tag.name}`} onClick={() => setEditing(true)}>
          Edit
        </Button>
        <Button
          variant="link"
          aria-label={`Delete #${tag.name}`}
          disabled={remove.isPending}
          onClick={onDelete}
        >
          Delete
        </Button>
      </span>
      <MutationError error={remove.error} what="tag" />
    </li>
  );
}
