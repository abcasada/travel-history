import { useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useId, useState } from "react";
import { Link, useParams } from "react-router";
import { errorKind, errorMessage, serverMessage } from "../api/errors";
import {
  getGetLegQueryKey,
  getListLegRoutesQueryKey,
  type LegOut,
  type RouteOut,
  type StopOut,
  useGetLeg,
  useGetTrip,
  useListLegRoutes,
  useProposeRoute,
  useSaveProposedRoute,
} from "../api/generated";
import { useMe } from "../auth/AuthGate";
import { type LngLat, useMapStore } from "../map/store";
import { useShellMode } from "../shells/useShellMode";
import { useInvalidateTrip } from "../trips/cache";
import { label, MODE_LABELS } from "../trips/labels";
import { paths } from "../trips/paths";
import { Button, Field, inputClass, Section } from "../ui/form";
import { QueryState } from "../ui/QueryState";
import { ENGINE_LABELS, FIX_THE_MAP_URL, formatDuration, useRoutingStore } from "./store";

/** Modes a car route fits; the server enforces the same list (trips/route_versions.py). */
const ROAD_MODES = new Set(["drive", "bus", "other"]);
const MAX_VIAS = 23; // the proxy takes 2-25 waypoints

// The drag editor is desktop-only and heavy: phones never download it (§18.1).
const RouteEditor = lazy(() => import("./editor/RouteEditor"));

type Via = { key: number; point: LngLat };
let viaSeq = 0;

/**
 * `/trips/:tripId/legs/:legId/route`: a leg's route versions (list pane); the map side is
 * LegRouteLayer. Item 25: "Propose a route" asks `/api/v1/routing/route` for a road route
 * from the leg's start stop through optional via points to its end stop, shows the provider
 * and its attribution, and saves the proposal as the leg's next version. Item 26: the drag
 * editor (`editor/RouteEditor`, desktop only) reshapes it on the map, its map half rendered
 * by LegRouteLayer.
 * Saved versions are frozen (rule 5): every save creates a new version, nothing re-routes one.
 */
export function LegRoutePage() {
  const { tripId, legId } = useParams();
  const id = Number(legId);
  const leg = useGetLeg(id, { query: { enabled: Number.isInteger(id) && id > 0 } });
  return (
    <div className="p-4">
      <Link to={paths.trip(Number(tripId))} className="text-sm text-blue-700 hover:underline">
        ← Back to the trip
      </Link>
      <QueryState query={leg} what="leg">
        {(data) => <LegRoute leg={data} />}
      </QueryState>
    </div>
  );
}

function LegRoute({ leg }: { leg: LegOut }) {
  const versions = useListLegRoutes(leg.id);
  const me = useMe();
  const canRoute = leg.can_edit && me.role !== "viewer";
  const { mode } = useShellMode();
  const editing = useRoutingStore((s) => s.editingLegId === leg.id);
  return (
    <>
      <h2 className="mt-2 mb-1 text-lg font-semibold">
        {label(MODE_LABELS, leg.mode)}: {leg.origin_label || "start"} →{" "}
        {leg.destination_label || "end"}
      </h2>
      {canRoute && ROAD_MODES.has(leg.mode) && !editing && <ProposeRoute leg={leg} />}
      {canRoute && ROAD_MODES.has(leg.mode) && mode === "desktop" && <EditorSlot leg={leg} />}
      {canRoute && !ROAD_MODES.has(leg.mode) && (
        <p className="mb-3 text-sm text-slate-600">
          Road routes are for drive, bus and other legs.
        </p>
      )}
      <h3 className="mb-1 font-medium">Route versions</h3>
      <QueryState query={versions} what="route">
        {(rows) =>
          rows.length === 0 ? (
            <p className="text-sm text-slate-600">No route saved yet.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {rows.map((r) => (
                <VersionRow key={r.id} route={r} />
              ))}
            </ul>
          )
        }
      </QueryState>
    </>
  );
}

function VersionRow({ route: r }: { route: RouteOut }) {
  return (
    <li>
      Version {r.version} · {r.kind} · {(r.length_m / 1000).toFixed(1)} km
      {r.is_current && <span className="text-green-700"> (current)</span>}
      {r.engine && (
        <span className="block text-xs text-slate-500">
          {ENGINE_LABELS[r.engine] ?? r.engine}
          {r.engine_version && ` ${r.engine_version}`}
          {r.engine_data_date && `, road data ${r.engine_data_date}`}
          {r.attribution && ` · ${r.attribution}`}
        </span>
      )}
    </li>
  );
}

function EditorSlot({ leg }: { leg: LegOut }) {
  const trip = useGetTrip(leg.trip_id);
  if (!trip.data) return null;
  const stops = trip.data.stops;
  return (
    <Suspense fallback={null}>
      <RouteEditor
        leg={leg}
        start={stopPoint(stops, leg.origin_stop_id)}
        end={stopPoint(stops, leg.destination_stop_id)}
      />
    </Suspense>
  );
}

function stopPoint(stops: StopOut[], stopId: number | null): LngLat | null {
  const stop = stops.find((s) => s.id === stopId);
  return stop ? { lon: stop.place.lon, lat: stop.place.lat } : null;
}

function routingError(error: unknown): string {
  // The proxy's own sentence explains 409 (expired), 422 (no road) and 503 (no provider).
  const kind = errorKind(error);
  if (kind === "conflict" || kind === "invalid" || kind === "server") {
    return serverMessage(error) ?? errorMessage(error, "route");
  }
  return errorMessage(error, "route");
}

function ProposeRoute({ leg }: { leg: LegOut }) {
  const trip = useGetTrip(leg.trip_id);
  const stops = trip.data?.stops ?? [];
  const start = stopPoint(stops, leg.origin_stop_id);
  const end = stopPoint(stops, leg.destination_stop_id);
  const [vias, setVias] = useState<Via[]>([]);
  const [note, setNote] = useState("");
  const noteId = useId();
  const startPick = useMapStore((s) => s.startPick);
  const picking = useMapStore((s) => s.pick?.label === "a via point");
  const { proposal, legId: shownLeg, waypoints, show, clear } = useRoutingStore();
  const propose = useProposeRoute();
  const save = useSaveProposedRoute();
  const client = useQueryClient();
  const invalidateTrip = useInvalidateTrip();

  // A proposal belongs to this page: drop it when the user leaves the leg.
  useEffect(() => clear, [clear]);

  if (trip.isLoading) return null;
  if (!start || !end) {
    return (
      <p className="mb-3 text-sm text-slate-600">
        Give this leg a start and an end stop (on the{" "}
        <Link className="text-blue-700 hover:underline" to={paths.edit(leg.trip_id)}>
          trip's edit page
        </Link>
        ) to propose a road route.
      </p>
    );
  }

  const current = shownLeg === leg.id ? proposal : null;
  const route = current?.routes[0];
  const points = [start, ...vias.map((v) => v.point), end];

  function ask() {
    save.reset();
    propose.mutate(
      { data: { waypoints: points.map((p) => [p.lon, p.lat]), profile: "auto" } },
      { onSuccess: (answer) => show(leg.id, points, answer) },
    );
  }

  function keep() {
    save.mutate(
      { legId: leg.id, data: { waypoints: waypoints.map((p) => [p.lon, p.lat]), note } },
      {
        onSuccess: async () => {
          clear();
          setNote("");
          await Promise.all([
            client.invalidateQueries({ queryKey: getGetLegQueryKey(leg.id) }),
            client.invalidateQueries({ queryKey: getListLegRoutesQueryKey(leg.id) }),
            invalidateTrip(leg.trip_id),
          ]);
        },
      },
    );
  }

  return (
    <Section title="Propose a route">
      <ol className="mb-2 space-y-1 text-sm" aria-label="Waypoints">
        <li>Start: {formatPoint(start)}</li>
        {vias.map((v, i) => (
          <li key={v.key} className="flex items-center gap-2">
            Via {i + 1}: {formatPoint(v.point)}
            <Button
              variant="link"
              aria-label={`Remove via ${i + 1}`}
              onClick={() => setVias(vias.filter((other) => other.key !== v.key))}
            >
              Remove
            </Button>
          </li>
        ))}
        <li>End: {formatPoint(end)}</li>
      </ol>
      <div className="mb-3 flex flex-wrap gap-2">
        <Button
          disabled={picking || vias.length >= MAX_VIAS}
          onClick={() =>
            startPick("a via point", (point) => {
              viaSeq += 1;
              setVias((old) => [...old, { key: viaSeq, point }]);
            })
          }
        >
          {picking ? "Click the map…" : "Add a via point"}
        </Button>
        <Button variant="primary" onClick={ask} disabled={propose.isPending}>
          {propose.isPending ? "Routing…" : "Propose a route"}
        </Button>
      </div>
      {propose.error != null && (
        <p className="mb-2 text-sm text-red-700" role="alert">
          {routingError(propose.error)}
        </p>
      )}
      {current && route && (
        <section className="mb-3 rounded border bg-slate-50 p-2 text-sm" aria-label="Proposal">
          <p className="font-medium">
            Proposed: {(route.distance / 1000).toFixed(1)} km, {formatDuration(route.duration)}
          </p>
          <p className="text-xs text-slate-600">
            By {ENGINE_LABELS[current.provenance.engine] ?? current.provenance.engine}
            {current.provenance.engine_version && ` ${current.provenance.engine_version}`}
            {current.provenance.data_date && `, road data ${current.provenance.data_date}`}
          </p>
          <p className="text-xs text-slate-600" data-testid="route-attribution">
            {current.provenance.attribution}
            {current.provenance.engine === "osrm-fossgis" && (
              <>
                {" · "}
                <a className="text-blue-700 hover:underline" href={FIX_THE_MAP_URL}>
                  Fix the map
                </a>
              </>
            )}
          </p>
          <div className="mt-2">
            <Field label="Note for this version" htmlFor={noteId}>
              <input
                id={noteId}
                className={inputClass}
                maxLength={255}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </Field>
            <Button variant="primary" onClick={keep} disabled={save.isPending}>
              Save as a new version
            </Button>
          </div>
          {save.error != null && (
            <p className="mt-1 text-sm text-red-700" role="alert">
              {routingError(save.error)}
            </p>
          )}
        </section>
      )}
    </Section>
  );
}

function formatPoint(p: LngLat): string {
  return `${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}`;
}
