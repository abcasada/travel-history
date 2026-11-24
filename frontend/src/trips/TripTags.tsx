import { type FormEvent, useState } from "react";
import {
  type TripDetailOut,
  useAddTripTag,
  useListTags,
  useListTripTags,
  useRemoveTripTag,
} from "../api/generated";
import { useMe } from "../auth/AuthGate";
import { Button, inputClass } from "../ui/form";
import { MutationError } from "../ui/QueryState";
import { useInvalidateTrip } from "./cache";

/**
 * Tags on a trip. Tags are per user: the owner's are the trip's own, participants add theirs
 * (shown with who added them). Anyone who may contribute adds one of their tags, or types a new
 * name (the API creates the tag). Removing follows the API's `can_remove`.
 */
export function TripTags({ trip }: { trip: TripDetailOut }) {
  const me = useMe();
  const invalidate = useInvalidateTrip();
  const rows = useListTripTags(trip.id);
  const mine = useListTags({ query: { enabled: trip.access.contribute } });
  const add = useAddTripTag();
  const remove = useRemoveTripTag();
  const [text, setText] = useState("");

  // The detail's own list renders at once; the per-tag `can_remove` arrives with listTripTags.
  const tags = rows.data ?? trip.tags.map((t) => ({ ...t, can_remove: false }));
  const onTrip = new Set(tags.filter((t) => t.author.id === me.id).map((t) => t.id));
  const suggestions = (mine.data ?? []).filter((t) => !onTrip.has(t.id));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const name = text.trim().replace(/^#/, "");
    if (!name) return;
    const existing = suggestions.find((t) => t.name.toLowerCase() === name.toLowerCase());
    add.mutate(
      { tripId: trip.id, data: existing ? { tag_id: existing.id } : { name } },
      {
        onSuccess: async () => {
          setText("");
          await invalidate(trip.id);
        },
      },
    );
  };

  if (tags.length === 0 && !trip.access.contribute) return null;
  return (
    <section className="mt-1" aria-label="Tags">
      <ul className="flex flex-wrap gap-2 text-sm">
        {tags.map((t) => (
          <li
            key={`${t.id}-${t.author.id}`}
            className="flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-blue-800"
            style={t.color ? { borderLeft: `4px solid ${t.color}` } : undefined}
          >
            #{t.name}
            {!t.by_owner && (
              <span className="text-xs text-slate-500">({t.author.display_name})</span>
            )}
            {t.can_remove && (
              <button
                type="button"
                className="text-slate-500 hover:text-red-700"
                aria-label={`Remove tag ${t.name}`}
                disabled={remove.isPending}
                onClick={() =>
                  remove.mutate(
                    { tripId: trip.id, tagId: t.id },
                    { onSuccess: () => invalidate(trip.id) },
                  )
                }
              >
                ×
              </button>
            )}
          </li>
        ))}
      </ul>
      {trip.access.contribute && (
        <form onSubmit={submit} className="mt-1 flex gap-2" aria-label="Add tag">
          <input
            aria-label="Tag name"
            placeholder="Add a tag…"
            className={`${inputClass} max-w-48`}
            list={`trip-${trip.id}-tag-suggestions`}
            maxLength={64}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <datalist id={`trip-${trip.id}-tag-suggestions`}>
            {suggestions.map((t) => (
              <option key={t.id} value={t.name} />
            ))}
          </datalist>
          <Button type="submit" disabled={!text.trim() || add.isPending}>
            Tag
          </Button>
        </form>
      )}
      <MutationError error={add.error ?? remove.error} what="tag" />
    </section>
  );
}
