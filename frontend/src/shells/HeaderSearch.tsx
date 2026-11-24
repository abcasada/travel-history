import type { Ref } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router";
import { readTripFilter, writeTripFilter } from "../trips/filter";
import { paths } from "../trips/paths";
import { useFollowedText } from "../trips/useFollowedText";

/** The trip list is on the map home and `/trips`; elsewhere the search box opens `/trips`. */
function onTripList(pathname: string): boolean {
  return pathname === "/" || pathname === paths.list;
}

/**
 * The desktop header's search box (ui.md §18.4, `/` focuses it). It searches trip titles: on
 * the trip list it edits the list's `q` in the URL (the same filter the list and map read);
 * from any other page, typing opens the trip list with that search. Esc leaves the box.
 */
export function HeaderSearch({ ref }: { ref?: Ref<HTMLInputElement> }) {
  const { pathname } = useLocation();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const listed = onTripList(pathname);
  const urlQ = listed ? readTripFilter(params).q : "";
  // Local text, so fast typing keeps every letter (useFollowedText).
  const [text, setText] = useFollowedText(urlQ);

  const onChange = (q: string) => {
    setText(q);
    if (listed) {
      setParams(writeTripFilter(params, { ...readTripFilter(params), q }), { replace: true });
    } else if (q.trim()) {
      navigate(`${paths.list}?${new URLSearchParams({ q })}`);
    }
  };

  return (
    <input
      ref={ref}
      type="search"
      aria-label="Search trips"
      placeholder="Search trips…  /"
      className="w-64 rounded-md border px-2 py-1 text-sm"
      value={text}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Escape") e.currentTarget.blur();
        // Enter shows the results without leaving the keyboard: j/k work once the box is left.
        if (e.key === "Enter") e.currentTarget.blur();
      }}
    />
  );
}
