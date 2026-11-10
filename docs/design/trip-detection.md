# Trip auto-detection

Moved from PLAN.md §11 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 11. Trip auto-detection

Per user; every threshold is a per-user preference.

| Setting | Default |
|---|---|
| home radius | 805 m (≈ 0.5 mi) |
| day-trip minimum distance from home | 80.5 km (50 mi) |
| day-trip minimum duration | 3 h |
| night window | 01:00–05:00 local |
| stay point: distance / time | 200 m / 20 min |
| minimum mode-segment duration | 3 min |

Algorithm:

1. **Home reference** for each moment = the person's confirmed home periods (or long stays,
   which count as "home" for detection while active).
2. **Overnight trips:** any night whose night location (§10.1) is farther than the home radius
   from home. Consecutive away nights merge into one trip. The trip starts at the last departure
   from home before the first away night and ends at the first return after the last one.
3. **Long day trips:** outings that leave the home radius and return the same day without an
   away night, with max distance ≥ 50 mi and duration ≥ 3 h.
4. Everything else stays raw history; any outing can be promoted to a trip manually.
5. **Segments inside a trip:** use Google's semantic segments where present (activity type →
   mode; visits → stops). Otherwise from raw points: stay-point detection (distance/time
   thresholds), then speed-based mode guesses on the moves between stays:
   - median speed over a 2-min window: < 2.5 m/s walk; 2.5–55 m/s drive (train/bus/boat only by
     user correction or Google's activity type); > 55 m/s or a jump > 100 km across a point gap
     → flight;
   - a mode change must persist ≥ 3 min; shorter blips are absorbed into the surrounding segment.
   Multiple mode segments per trip are normal (walk–drive–flight–drive–walk).
6. **Legs** split at mode changes (and at stays of ≥ 2 h). Flying legs are matched to imported
   flights by time overlap and departure/arrival airport proximity (≤ 30 km); matched flights
   supply airline/flight number and the great-circle route.
7. **Drive legs** are map-matched with Valhalla `trace_route` → route kind `map_matched`.
8. Candidates get a fingerprint `hash(owner, start rounded to 1 h, end rounded to 1 h)`; candidates
   matching a `rejected_candidate` (or overlapping a confirmed/locked trip) are dropped.
9. Detection re-runs only touch unlocked candidates in affected ranges.

**Review queue** (desktop, keyboard-driven): accept / merge with neighbor / split at a point /
reject, then bulk tag and set purpose. Accepting confirms and locks the trip.
