import { type FormEvent, useState } from "react";
import { fieldErrors } from "../api/errors";
import {
  type NoteOut,
  type TripDetailOut,
  useAddNote,
  useDeleteNote,
  useListNotes,
  useUpdateNote,
} from "../api/generated";
import { Button, Field, inputClass, Section } from "../ui/form";
import { MutationError } from "../ui/QueryState";
import { useInvalidateTrip } from "./cache";

export function validateNote(body: string): Record<string, string> {
  return body.trim() ? {} : { body: "Write something first." };
}

/** Notes on a trip: everyone who sees the trip reads them; the owner and participants (Members)
 * add their own, and edit or delete them as the API's flags allow. */
export function NotesSection({ trip }: { trip: TripDetailOut }) {
  const notes = useListNotes(trip.id);
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const invalidate = useInvalidateTrip();
  const remove = useDeleteNote();
  const rows = notes.data ?? [];

  const onDelete = (note: NoteOut) => {
    if (!window.confirm("Delete this note?")) return;
    remove.mutate({ noteId: note.id }, { onSuccess: () => invalidate(trip.id) });
  };

  return (
    <Section
      title="Notes"
      actions={
        trip.access.contribute &&
        editing === null && (
          <Button onClick={() => setEditing("new")} aria-label="Add note">
            + Note
          </Button>
        )
      }
    >
      {notes.isError && <p className="text-sm text-red-700">Couldn't load the notes.</p>}
      {rows.length === 0 && editing !== "new" && notes.isSuccess && (
        <p className="text-sm text-slate-600">No notes yet.</p>
      )}
      <ul className="space-y-2">
        {rows.map((note) =>
          editing === note.id ? (
            <li key={note.id}>
              <NoteForm trip={trip} note={note} onDone={() => setEditing(null)} />
            </li>
          ) : (
            <li key={note.id} className="rounded border px-3 py-2 text-sm">
              <p className="whitespace-pre-wrap">{note.body}</p>
              <p className="mt-1 flex gap-3 text-xs text-slate-500">
                <span>
                  {note.author.display_name} · {new Date(note.created_at).toLocaleDateString()}
                </span>
                {note.can_edit && editing === null && (
                  <Button
                    variant="link"
                    aria-label={`Edit note by ${note.author.display_name}`}
                    onClick={() => setEditing(note.id)}
                  >
                    Edit
                  </Button>
                )}
                {note.can_delete && (
                  <Button
                    variant="link"
                    aria-label={`Delete note by ${note.author.display_name}`}
                    disabled={remove.isPending}
                    onClick={() => onDelete(note)}
                  >
                    Delete
                  </Button>
                )}
              </p>
            </li>
          ),
        )}
      </ul>
      <MutationError error={remove.error} what="note" />
      {editing === "new" && <NoteForm trip={trip} onDone={() => setEditing(null)} />}
    </Section>
  );
}

function NoteForm({
  trip,
  note,
  onDone,
}: {
  trip: TripDetailOut;
  note?: NoteOut;
  onDone: () => void;
}) {
  const [body, setBody] = useState(note?.body ?? "");
  const [shown, setShown] = useState<Record<string, string>>({});
  const invalidate = useInvalidateTrip();
  const add = useAddNote();
  const update = useUpdateNote();
  const mutation = note ? update : add;
  const errors = { ...fieldErrors(mutation.error), ...shown };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const problems = validateNote(body);
    setShown(problems);
    if (Object.keys(problems).length) return;
    const done = {
      onSuccess: async () => {
        await invalidate(trip.id);
        onDone();
      },
    };
    if (note) update.mutate({ noteId: note.id, data: { body } }, done);
    else add.mutate({ tripId: trip.id, data: { body } }, done);
  };

  return (
    <form
      onSubmit={submit}
      noValidate
      aria-label={note ? "Edit note" : "New note"}
      className="my-2 rounded border bg-slate-50 p-3"
    >
      <Field label="Note" htmlFor={`note-${note?.id ?? "new"}`} error={errors.body}>
        <textarea
          id={`note-${note?.id ?? "new"}`}
          className={inputClass}
          rows={3}
          maxLength={20000}
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
      </Field>
      <MutationError
        error={Object.keys(fieldErrors(mutation.error)).length ? null : mutation.error}
        what="note"
      />
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={mutation.isPending}>
          {note ? "Save note" : "Add note"}
        </Button>
        <Button onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}
