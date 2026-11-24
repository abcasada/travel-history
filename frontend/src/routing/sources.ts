/**
 * What a hand-edited version is made of, for the version list (`Route.sources`, D-93 (3),
 * item 27). The server writes one entry per source: a cached proposal it verified, a slice of an
 * earlier version of the leg, or points the editor sent as drawn (unverified, sometimes with an
 * engine claim that only adds that provider's credit). The list says which parts were checked.
 */
import { ENGINE_LABELS } from "./store";

type Entry = { [key: string]: unknown };

const engineName = (engine: unknown): string =>
  typeof engine === "string" && engine ? (ENGINE_LABELS[engine] ?? engine) : "";

const pointCount = (n: unknown): string => {
  const count = typeof n === "number" ? n : 0;
  return `${count.toLocaleString("en-US")} ${count === 1 ? "point" : "points"}`;
};

/** One sentence fragment per source, in the order the server listed them. */
export function describeSources(sources: readonly Entry[] | undefined | null): string[] {
  return (sources ?? []).map((s) => {
    const points = pointCount(s.points);
    const engine = engineName(s.engine);
    const checked = s.verified === true ? "checked" : "not checked";
    switch (s.source) {
      case "proposal":
        return `${engine || "routed"} route, ${points}, ${checked}`;
      case "version": {
        const kind = typeof s.kind === "string" && s.kind ? `, ${s.kind}` : "";
        return `version ${String(s.version ?? "?")}${kind}, ${points}`;
      }
      case "drawn":
        return engine
          ? `${points} sent by the editor (${engine} route that had expired), ${checked}`
          : `${points} drawn by hand, ${checked}`;
      default:
        return `${points}, ${checked}`;
    }
  });
}
