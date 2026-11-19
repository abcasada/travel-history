import { useListDatasets } from "../api/generated";

/** Data sources and their licenses (PLAN.md §27): OpenFlights' ODbL asks for this credit. */
export function AboutPage() {
  const datasets = useListDatasets();

  return (
    <div className="space-y-4 p-4">
      <div>
        <h2 className="text-lg font-semibold">About and data sources</h2>
        <p className="text-sm text-slate-600">
          Reference data this app uses, with the version loaded and its license. Map credits are
          shown in the corner of the map.
        </p>
      </div>
      {datasets.isLoading && <p className="text-sm text-slate-600">Loading…</p>}
      {datasets.isError && <p className="text-sm text-red-700">Couldn't load the list.</p>}
      {datasets.data && datasets.data.length === 0 && (
        <p className="text-sm text-slate-600">No reference datasets are loaded yet.</p>
      )}
      <ul className="space-y-3">
        {datasets.data?.map((dataset) => (
          <li key={dataset.name} className="rounded border p-3 text-sm">
            <p className="font-medium">{dataset.attribution || dataset.title}</p>
            <p className="text-slate-600">
              {dataset.title}: version {dataset.version || "unknown"},{" "}
              {dataset.row_count.toLocaleString()} rows
            </p>
            <p>
              License:{" "}
              {dataset.license_url ? (
                <a className="underline" href={dataset.license_url} rel="noreferrer">
                  {dataset.license}
                </a>
              ) : (
                dataset.license
              )}
              {dataset.homepage_url && (
                <>
                  {" · "}
                  <a className="underline" href={dataset.homepage_url} rel="noreferrer">
                    Source
                  </a>
                </>
              )}
            </p>
          </li>
        ))}
      </ul>
      <section aria-label="Code from other projects" className="text-sm">
        <h3 className="mb-1 font-medium">Code from other projects</h3>
        <p>
          The route editor's anchor routing is ported from{" "}
          <a className="underline" href="https://github.com/gpxstudio/gpx.studio" rel="noreferrer">
            gpx.studio
          </a>{" "}
          (© 2026 gpx.studio, MIT License).
        </p>
      </section>
    </div>
  );
}
