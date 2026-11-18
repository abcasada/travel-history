import { Link, useParams } from "react-router";
import { type LegOut, useGetLeg, useListLegRoutes } from "../api/generated";
import { label, MODE_LABELS } from "../trips/labels";
import { paths } from "../trips/paths";
import { QueryState } from "../ui/QueryState";

/**
 * `/trips/:tripId/legs/:legId/route`: a leg's route versions (list pane); the map side is
 * LegRouteLayer. This page is the slot for the routing work:
 * - item 25 (routing proxy, manual trips): "Propose a route" calls `/api/v1/routing/route` from
 *   the leg's end points and saves the result as a new version;
 * - item 26 (drag editor): `<RouteEditor leg={leg} />` replaces the placeholder below, with its
 *   map half rendered by LegRouteLayer.
 * Saved versions are frozen (rule 5): every edit creates a new version, nothing re-routes one.
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
  return (
    <>
      <h2 className="mt-2 mb-1 text-lg font-semibold">
        {label(MODE_LABELS, leg.mode)}: {leg.origin_label || "start"} →{" "}
        {leg.destination_label || "end"}
      </h2>
      <p className="mb-3 text-sm text-slate-600">
        Drawing and editing routes arrives with the routing editor. Until then the map shows this
        leg as a dashed straight line between its stops.
      </p>
      <h3 className="mb-1 font-medium">Route versions</h3>
      <QueryState query={versions} what="route">
        {(rows) =>
          rows.length === 0 ? (
            <p className="text-sm text-slate-600">No route saved yet.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {rows.map((r) => (
                <li key={r.id}>
                  Version {r.version} · {r.kind} · {(r.length_m / 1000).toFixed(1)} km
                  {r.is_current && <span className="text-green-700"> (current)</span>}
                </li>
              ))}
            </ul>
          )
        }
      </QueryState>
    </>
  );
}
