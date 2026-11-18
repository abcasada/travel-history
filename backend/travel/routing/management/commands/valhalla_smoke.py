"""Smoke-test the self-hosted Valhalla from the app's network (docs/valhalla.md).

./dev valhalla smoke        # route between two Kansas towns, then map-match a synthetic track

The track is generated here from the route itself (resampled, jittered, timestamped), so no
location data is stored anywhere. Exits non-zero on any failure.
"""

import math
import random
import time

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from travel.routing.coverage import in_valhalla_coverage

# Public town centres (lon, lat), not anyone's places.
WICHITA = (-97.3301, 37.6872)
SALINA = (-97.6114, 38.8403)
HEADERS = {"User-Agent": "travel-history/valhalla-smoke"}
EARTH_RADIUS_M = 6_371_000.0


def _metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat = math.radians((a[1] + b[1]) / 2)
    dx = math.radians(b[0] - a[0]) * math.cos(lat)
    dy = math.radians(b[1] - a[1])
    return EARTH_RADIUS_M * math.hypot(dx, dy)


def synthetic_track(
    line: list[list[float]], spacing_m: float = 50.0, jitter_m: float = 8.0, speed_mps: float = 25.0
) -> list[dict]:
    """Points every `spacing_m` along `line`, jittered by up to `jitter_m`, at `speed_mps`."""
    rng = random.Random(17)
    t0 = 1_700_000_000
    out: list[dict] = []
    walked = 0.0
    next_at = 0.0
    for a, b in zip(line, line[1:], strict=False):
        seg = _metres(a, b)
        while seg > 0 and next_at <= walked + seg:
            f = (next_at - walked) / seg
            lon = a[0] + (b[0] - a[0]) * f
            lat = a[1] + (b[1] - a[1]) * f
            dlat = rng.uniform(-jitter_m, jitter_m) / 111_320
            dlon = rng.uniform(-jitter_m, jitter_m) / (111_320 * math.cos(math.radians(lat)))
            out.append(
                {"lon": lon + dlon, "lat": lat + dlat, "time": t0 + int(next_at / speed_mps)}
            )
            next_at += spacing_m
        walked += seg
    return out


class Command(BaseCommand):
    help = "Route and map-match against VALHALLA_URL (Kansas development tiles)."

    def _post(self, path: str, body: dict) -> tuple[dict, float]:
        started = time.monotonic()
        resp = requests.post(
            f"{settings.VALHALLA_URL}{path}", json=body, headers=HEADERS, timeout=60
        )
        elapsed = time.monotonic() - started
        if resp.status_code != 200:
            raise CommandError(f"{path} answered {resp.status_code}: {resp.text[:300]}")
        return resp.json(), elapsed

    def handle(self, *_args, **_options):
        status = requests.get(f"{settings.VALHALLA_URL}/status", headers=HEADERS, timeout=10)
        status.raise_for_status()
        self.stdout.write(f"status: {status.json()}")

        if not in_valhalla_coverage([WICHITA, SALINA]):
            raise CommandError("the test towns are outside the coverage polygon")

        route, route_s = self._post(
            "/route",
            {
                "locations": [
                    {"lon": WICHITA[0], "lat": WICHITA[1]},
                    {"lon": SALINA[0], "lat": SALINA[1]},
                ],
                "costing": "auto",
                "format": "osrm",
                "shape_format": "geojson",
            },
        )
        if route.get("code") != "Ok":
            raise CommandError(f"route failed: {route}")
        best = route["routes"][0]
        km = best["distance"] / 1000
        line = best["geometry"]["coordinates"]
        self.stdout.write(
            f"route Wichita -> Salina: {km:.1f} km, {best['duration'] / 60:.0f} min, "
            f"{len(line)} vertices, {route_s * 1000:.0f} ms"
        )
        if not 130 <= km <= 200:
            raise CommandError(f"implausible route length {km:.1f} km")

        track = synthetic_track(line)
        match, match_s = self._post(
            "/trace_route",
            {
                "shape": track,
                "costing": "auto",
                "shape_match": "map_snap",
                "use_timestamps": True,
                "trace_options": {"search_radius": 50},
                "format": "osrm",
                "shape_format": "geojson",
            },
        )
        if match.get("code") != "Ok" or not match.get("matchings"):
            raise CommandError(f"map-match failed: {str(match)[:300]}")
        matched_km = sum(m["distance"] for m in match["matchings"]) / 1000
        self.stdout.write(
            f"map-match of {len(track)} synthetic points: {len(match['matchings'])} matching(s), "
            f"{matched_km:.1f} km, {match_s * 1000:.0f} ms"
        )
        if abs(matched_km - km) > 0.05 * km:
            raise CommandError(f"matched {matched_km:.1f} km vs routed {km:.1f} km (> 5 % apart)")
        self.stdout.write(self.style.SUCCESS("valhalla smoke test passed"))
