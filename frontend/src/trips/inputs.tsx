/** Inputs the trip editors share: a place (map pick, city, airport, or typed coordinates),
 * airport and city searches, and a local date-time in an IANA zone. */
import { useId, useState } from "react";
import {
  type AirportOut,
  type GazetteerPlaceOut,
  useSearchAirports,
  useSearchPlaces,
} from "../api/generated";
import { browserZone, isValidZone } from "../lib/time";
import { type LngLat, useMapStore } from "../map/store";
import { Button, inputClass } from "../ui/form";

export function airportLabel(a: AirportOut): string {
  const code = a.iata_code || a.icao_code || a.ident;
  return `${code} ${a.name}${a.municipality ? `, ${a.municipality}` : ""}`;
}

/** Type a code, name or city; pick one of the matches. */
export function AirportSearch({
  label,
  onSelect,
}: {
  label: string;
  onSelect: (airport: AirportOut) => void;
}) {
  const id = useId();
  const [q, setQ] = useState("");
  const term = q.trim();
  const results = useSearchAirports(
    { q: term, limit: 8 },
    { query: { enabled: term.length >= 2, staleTime: 5 * 60_000 } },
  );
  return (
    <div className="relative">
      <input
        id={id}
        type="search"
        aria-label={label}
        placeholder="Airport code, name or city"
        className={inputClass}
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {term.length >= 2 && results.data && (
        <ul className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded border bg-white shadow">
          {results.data.length === 0 && (
            <li className="px-2 py-1 text-sm text-slate-500">No airports match.</li>
          )}
          {results.data.map((a) => (
            <li key={a.id}>
              <button
                type="button"
                className="block w-full px-2 py-1 text-left text-sm hover:bg-slate-100"
                onClick={() => {
                  onSelect(a);
                  setQ("");
                }}
              >
                {airportLabel(a)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The name a chosen city gives a stop: "Wichita, KS" in the US, "Paris, France" elsewhere. */
export function cityLabel(p: GazetteerPlaceOut): string {
  const region = p.country_code === "US" ? p.admin1_code : p.country || p.country_code;
  return region ? `${p.name}, ${region}` : p.name;
}

function cityDetail(p: GazetteerPlaceOut): string {
  const where = [p.admin1, p.country].filter(Boolean).join(", ");
  const people = p.population > 0 ? ` · ${p.population.toLocaleString()} people` : "";
  return `${p.name}${where ? `, ${where}` : ""}${people}`;
}

/** Type a city or town ("Paris, TX" narrows by state or country); pick one of the matches.
 * Searches the server's own GeoNames copy: nothing typed here leaves the server (D-20). */
export function CitySearch({
  label,
  onSelect,
}: {
  label: string;
  onSelect: (place: GazetteerPlaceOut) => void;
}) {
  const id = useId();
  const [q, setQ] = useState("");
  const term = q.trim();
  const results = useSearchPlaces(
    { q: term, limit: 8 },
    { query: { enabled: term.length >= 2, staleTime: 5 * 60_000 } },
  );
  return (
    <div className="relative">
      <input
        id={id}
        type="search"
        aria-label={label}
        placeholder="Find a city or town"
        className={inputClass}
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {term.length >= 2 && results.data && (
        <ul className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded border bg-white shadow">
          {results.data.length === 0 && (
            <li className="px-2 py-1 text-sm text-slate-500">No places match.</li>
          )}
          {results.data.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                className="block w-full px-2 py-1 text-left text-sm hover:bg-slate-100"
                onClick={() => {
                  onSelect(p);
                  setQ("");
                }}
              >
                {cityDetail(p)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** "37.69, -97.33" (lat, lon, as maps show them) -> a point, else null. */
export function parseLatLon(text: string): LngLat | null {
  const m = /^\s*(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)\s*$/.exec(text);
  if (!m) return null;
  const lat = Number(m[1]);
  const lon = Number(m[2]);
  return Math.abs(lat) <= 90 && Math.abs(lon) <= 180 ? { lon, lat } : null;
}

export function formatPoint(p: LngLat): string {
  return `${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}`;
}

/**
 * Where something is: click "Pick on map" and then the map, find a city, choose an airport, or
 * paste coordinates. A city also suggests a name and its time zone. There is no street-address
 * search: that would need a hosted geocoder (D-20 keeps geocoding offline).
 */
export function PlaceInput({
  value,
  onChange,
  pickLabel,
  error,
}: {
  value: LngLat | null;
  onChange: (point: LngLat, name?: string, zone?: string) => void;
  pickLabel: string;
  error?: string;
}) {
  const id = useId();
  const startPick = useMapStore((s) => s.startPick);
  const picking = useMapStore((s) => s.pick?.label === pickLabel);
  const [text, setText] = useState("");
  const typed = parseLatLon(text);
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className={value ? "" : "text-slate-500"} data-testid="place-point">
          {value ? formatPoint(value) : "No location yet"}
        </span>
        <Button onClick={() => startPick(pickLabel, (p) => onChange(p))} disabled={picking}>
          {picking ? "Click the map…" : "Pick on map"}
        </Button>
      </div>
      <CitySearch
        label={`City for ${pickLabel}`}
        onSelect={(p) =>
          onChange({ lon: p.lon, lat: p.lat }, cityLabel(p), p.timezone || undefined)
        }
      />
      <AirportSearch
        label={`Airport for ${pickLabel}`}
        onSelect={(a) => onChange({ lon: a.lon, lat: a.lat }, airportLabel(a))}
      />
      <div className="flex gap-2">
        <input
          id={id}
          aria-label={`Coordinates for ${pickLabel}`}
          placeholder="or coordinates: lat, lon"
          className={inputClass}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <Button
          disabled={!typed}
          onClick={() => {
            if (typed) onChange(typed);
            setText("");
          }}
        >
          Use
        </Button>
      </div>
      {error && <p className="text-xs text-red-700">{error}</p>}
    </div>
  );
}

let zones: string[] | null = null;
function allZones(): string[] {
  if (!zones) {
    const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
    zones = intl.supportedValuesOf?.("timeZone") ?? [browserZone()];
  }
  return zones;
}

/** A wall-clock time and its zone; both strings ("" = no time). Convert with lib/time. */
export function ZonedTimeInput({
  label,
  local,
  zone,
  onChange,
  error,
}: {
  label: string;
  local: string;
  zone: string;
  onChange: (local: string, zone: string) => void;
  error?: string;
}) {
  const id = useId();
  const listId = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-0.5 block text-sm font-medium text-slate-700">
        {label}
      </label>
      <div className="flex gap-1">
        <input
          id={id}
          type="datetime-local"
          className={inputClass}
          value={local}
          onChange={(e) => onChange(e.target.value, zone || browserZone())}
        />
        <input
          aria-label={`${label} time zone`}
          className={`${inputClass} max-w-40`}
          list={listId}
          value={zone}
          onChange={(e) => onChange(local, e.target.value)}
        />
        <datalist id={listId}>
          {allZones().map((z) => (
            <option key={z} value={z} />
          ))}
        </datalist>
      </div>
      {(error || (zone && !isValidZone(zone))) && (
        <p className="mt-0.5 text-xs text-red-700">{error ?? "Unknown time zone."}</p>
      )}
    </div>
  );
}
