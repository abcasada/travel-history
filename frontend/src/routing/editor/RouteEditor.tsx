import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";
import { errorMessage, serverMessage } from "../../api/errors";
import {
  getGetLegQueryKey,
  getListLegRoutesQueryKey,
  getRoute,
  type LegOut,
} from "../../api/generated";
import type { LngLat } from "../../map/store";
import { useShortcuts } from "../../platform/shortcuts";
import { useInvalidateTrip } from "../../trips/cache";
import { Button, Field, inputClass, Section } from "../../ui/form";
import { useRoutingStore } from "../store";
import { useEditorStore } from "./editorStore";
import type { Coord } from "./geometry";
import {
  anchors,
  attributions,
  controlPoints,
  type EditorState,
  fromDrawn,
  fromLine,
} from "./model";

/**
 * The drag editor's toolbar in the list pane (lazy, desktop only; routing.md §13.4). "Reshape
 * on the map" starts from the unsaved proposal, else the current version, else a straight line
 * between the leg's stops; the map side is RouteEditorLayer. Saving creates a new frozen
 * version (rule 5) through `saveEditedRoute` (D-93).
 */
export default function RouteEditor({
  leg,
  start,
  end,
}: {
  leg: LegOut;
  start: LngLat | null;
  end: LngLat | null;
}) {
  const editingLegId = useRoutingStore((s) => s.editingLegId);
  const setEditing = useRoutingStore((s) => s.setEditing);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const editing = editingLegId === leg.id;

  // Leaving the page closes the editor (unsaved edits are dropped, like an unsaved proposal).
  useEffect(
    () => () => {
      useRoutingStore.getState().setEditing(null);
      useEditorStore.getState().stop();
    },
    [],
  );

  async function open() {
    setLoadError(null);
    setLoading(true);
    try {
      const state = await initialState(leg, start, end);
      if (!state) {
        setLoadError("Give this leg a start and an end stop first.");
        return;
      }
      useEditorStore.getState().start(leg.id, state);
      setEditing(leg.id);
    } catch (error) {
      setLoadError(errorMessage(error, "route"));
    } finally {
      setLoading(false);
    }
  }

  if (!editing) {
    return (
      <Section title="Reshape on the map">
        <p className="mb-2 text-sm text-slate-600">
          Drag the line or its points to change the roads; only the changed part is routed again.
        </p>
        <Button onClick={open} disabled={loading}>
          {loading ? "Loading…" : "Reshape on the map"}
        </Button>
        {loadError && (
          <p className="mt-1 text-sm text-red-700" role="alert">
            {loadError}
          </p>
        )}
      </Section>
    );
  }
  return <Toolbar leg={leg} />;
}

async function initialState(
  leg: LegOut,
  start: LngLat | null,
  end: LngLat | null,
): Promise<EditorState | null> {
  const shown = useRoutingStore.getState();
  const proposal = shown.legId === leg.id ? shown.proposal : null;
  if (proposal?.routes[0]) {
    const waypoints = shown.waypoints.map((p): [number, number] => [p.lon, p.lat]);
    return fromLine(
      proposal.routes[0].geometry.coordinates as [number, number][],
      {
        kind: "proposal",
        waypoints,
        engine: proposal.provenance.engine,
        attribution: proposal.provenance.attribution,
      },
      waypoints,
    );
  }
  if (leg.current_route_id) {
    const route = await getRoute(leg.current_route_id);
    const line = route.geometry.coordinates.flat() as unknown as [number, number][];
    const controls = route.waypoints.map((w): Coord => [Number(w.lon), Number(w.lat)]);
    return fromLine(
      line,
      { kind: "version", routeId: route.id, engine: route.engine, attribution: route.attribution },
      controls,
    );
  }
  if (start && end) {
    return fromDrawn([
      [start.lon, start.lat],
      [end.lon, end.lat],
    ]);
  }
  return null;
}

function Toolbar({ leg }: { leg: LegOut }) {
  const { state, past, future, busy, error, saveStatus, undo, redo, save, stop } = useEditorStore();
  const setEditing = useRoutingStore((s) => s.setEditing);
  const clearProposal = useRoutingStore((s) => s.clear);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const noteId = useId();
  const client = useQueryClient();
  const invalidateTrip = useInvalidateTrip();

  useShortcuts({ u: undo, U: redo });

  function close() {
    stop();
    setEditing(null);
  }

  async function keep() {
    setSaving(true);
    setSaveError(null);
    try {
      await save(note);
      clearProposal();
      close();
      await Promise.all([
        client.invalidateQueries({ queryKey: getGetLegQueryKey(leg.id) }),
        client.invalidateQueries({ queryKey: getListLegRoutesQueryKey(leg.id) }),
        invalidateTrip(leg.trip_id),
      ]);
    } catch (failure) {
      setSaveError(serverMessage(failure) ?? errorMessage(failure, "route"));
    } finally {
      setSaving(false);
    }
  }

  const credits = attributions(state);
  return (
    <Section title="Reshape on the map">
      <ul className="mb-2 list-disc pl-5 text-xs text-slate-600">
        <li>Drag a point, or drag the line, to route through a new place.</li>
        <li>Click the line to add a point; click the map to extend the end.</li>
        <li>Click a point for its menu; shift-click or right-click removes it.</li>
        <li>On a touch screen, drag a point, tap it for its menu, or hold the line to drag it.</li>
      </ul>
      <p className="mb-2 text-sm" data-testid="editor-status">
        {busy
          ? "Routing…"
          : `${state.points.length} points, ${controlPoints(state).length} fixed of ${anchors(state).length} handles`}
      </p>
      {error && (
        <p className="mb-2 text-sm text-red-700" role="alert">
          {error}
        </p>
      )}
      <div className="mb-2 flex flex-wrap gap-2">
        <Button onClick={undo} disabled={busy || past.length === 0} aria-keyshortcuts="u">
          Undo
        </Button>
        <Button onClick={redo} disabled={busy || future.length === 0} aria-keyshortcuts="Shift+U">
          Redo
        </Button>
        <Button variant="link" onClick={close}>
          Discard changes
        </Button>
      </div>
      {credits.length > 0 && (
        <p className="mb-2 text-xs text-slate-600" data-testid="editor-attribution">
          {credits.join("; ")}
        </p>
      )}
      <Field label="Note for this version" htmlFor={noteId}>
        <input
          id={noteId}
          className={inputClass}
          maxLength={255}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </Field>
      <Button
        variant="primary"
        onClick={keep}
        disabled={busy || saving || past.length === 0 || state.points.length < 2}
      >
        {saving ? "Saving…" : "Save the edited route"}
      </Button>
      {saving && saveStatus && (
        <p className="mt-1 text-sm text-slate-600" role="status">
          {saveStatus}
        </p>
      )}
      {saveError && (
        <p className="mt-1 text-sm text-red-700" role="alert">
          {saveError}
        </p>
      )}
    </Section>
  );
}
