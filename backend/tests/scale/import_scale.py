"""Realistic-size Timeline import test on the dev stack (work-order item 3 / audit finding #4).

SYNTHETIC: every place is a jittered public city centre; no real history is involved.

Run through `./dev import-scale-test` (scripts/import-scale-test.sh), which also measures the
worker's memory. Subcommands, run in the `tools` container (owner role, /bulk mounted):

    generate <path> <size_mb>   stream an Android on-device export of about size_mb to <path>
    run <path> <results.json>   upload it over HTTP as a throwaway user, wait for the worker,
                                record stage times, DB growth, counts and tile timings
    cleanup                     delete the throwaway user, all its rows and its bulk files

The throwaway user (SCALE_EMAIL) exists only for this test, so cleanup never touches anyone
else's data. Not collected by pytest (no test_ prefix); the quick suite never runs it."""

from __future__ import annotations

import datetime as dt
import hashlib
import http.client
import json
import math
import os
import random
import secrets
import shutil
import sys
import time
from pathlib import Path

SCALE_EMAIL = "scale-test@example.invalid"
OFFSET_MIN = -360  # a fixed offset is enough for synthetic data
ZONE = dt.timezone(dt.timedelta(minutes=OFFSET_MIN))
FIRST_DAY = dt.datetime(2016, 1, 1, tzinfo=ZONE)
HOME = (37.6872, -97.3301)  # public city centres (synthetic), as in tests/synth/timeline.py
WORK = (37.7200, -97.2900)
TRIP_CITIES = [(38.8403, -97.6114), (39.0997, -94.5786), (39.7392, -104.9903)]
RAW_EVERY_S = 60  # raw position fixes during waking hours
SCAN_EVERY_S = 300  # wifiScan + activityRecord (not imported, but they make up the bytes)

HISTORY_TABLES = [
    "history_locationpoint",
    "history_timelinesegment",
    "history_placehint",
    "history_importbatch",
    "history_rawfile",
    "history_uploadsession",
    "history_coveragereport",
]
TILE_ZOOMS = [0, 3, 6, 10, 16]


# --- generation -------------------------------------------------------------------------------


def _iso(epoch: float) -> str:
    when = dt.datetime.fromtimestamp(epoch, ZONE)
    return when.isoformat(timespec="milliseconds")


def _deg(lat: float, lon: float) -> str:
    return f'"{lat:.7f}°, {lon:.7f}°"'


class _Day:
    """One synthetic day: a list of (start, end, from, to) legs; stays have from == to."""

    def __init__(self, rng: random.Random, start: float, trip: tuple | None):
        self.rng = rng
        h = 3600
        if trip is None:
            errand = (HOME[0] + rng.uniform(-0.05, 0.05), HOME[1] + rng.uniform(-0.05, 0.05))
            self.stays = [
                (start, start + 7.5 * h, HOME, "HOME"),
                (start + 8 * h, start + 17 * h, WORK, "WORK"),
                (start + 17.5 * h, start + 19 * h, errand, "UNKNOWN"),
                (start + 19.5 * h, start + 24 * h, HOME, "HOME"),
            ]
            self.nested = (start + 12 * h, start + 12.75 * h, WORK)
        else:
            here, there = trip
            self.stays = [
                (start, start + 8 * h, here, "UNKNOWN" if here != HOME else "HOME"),
                (start + 13 * h, start + 24 * h, there, "UNKNOWN" if there != HOME else "HOME"),
            ]
            self.nested = None

    def where(self, epoch: float) -> tuple[float, float]:
        stays = self.stays
        for i, (s0, s1, place, _) in enumerate(stays):
            if s0 <= epoch < s1:
                return place
            if i + 1 < len(stays) and s1 <= epoch < stays[i + 1][0]:
                f = (epoch - s1) / (stays[i + 1][0] - s1)
                nxt = stays[i + 1][2]
                return (place[0] + f * (nxt[0] - place[0]), place[1] + f * (nxt[1] - place[1]))
        return stays[-1][2]


def generate(path: Path, size_mb: int) -> dict:
    """Stream the export: segments go straight to `path`, raw signals to a side file appended at
    the end, so memory stays flat and the size target is met without a second pass."""
    rng = random.Random(20261117)  # noqa: S311 - reproducible synthetic data, not secrets
    target = size_mb * 1024 * 1024
    side = path.with_suffix(".rawsignals.tmp")
    counts = {"segments": 0, "visit": 0, "activity": 0, "path": 0, "memory": 0}
    counts |= {"path_points": 0, "raw_positions": 0, "other_signals": 0, "days": 0}
    mac_base = rng.randrange(1 << 40)

    with path.open("w", encoding="utf-8") as seg, side.open("w", encoding="utf-8") as raw:
        seg.write('{"SYNTHETIC": "generated test data (import scale test)", "semanticSegments": [')
        raw_first = seg_first = True
        written = 0
        day = 0
        trip_left = 0
        here = HOME

        def emit_seg(text: str) -> None:
            nonlocal seg_first, written
            seg.write(text if seg_first else "," + text)
            seg_first = False
            written += len(text) + 1
            counts["segments"] += 1

        def emit_raw(text: str) -> None:
            nonlocal raw_first, written
            raw.write(text if raw_first else "," + text)
            raw_first = False
            written += len(text) + 1

        def times(a: float, b: float) -> str:
            return (
                f'"startTime": "{_iso(a)}", "endTime": "{_iso(b)}", '
                f'"startTimeTimezoneUtcOffsetMinutes": {OFFSET_MIN}, '
                f'"endTimeTimezoneUtcOffsetMinutes": {OFFSET_MIN}'
            )

        while written < target:
            start = (FIRST_DAY + dt.timedelta(days=day)).timestamp()
            trip = None
            if trip_left == 0 and day % 30 == 29:
                trip_left, there = 3, rng.choice(TRIP_CITIES)
                trip = (HOME, there)
                here = there
            elif trip_left == 1:
                trip = (here, HOME)
                here = HOME
            if trip_left:
                trip_left -= 1
            plan = _Day(rng, start, trip)

            for i, (s0, s1, place, semantic) in enumerate(plan.stays):
                pid = f"ChIJsynthetic{place[0]:.3f}_{place[1]:.3f}"
                emit_seg(
                    "{"
                    + times(s0, s1)
                    + ', "visit": {"hierarchyLevel": 0, "probability": 0.9, "topCandidate": '
                    f'{{"placeId": "{pid}", "semanticType": "{semantic}", "probability": 0.8, '
                    f'"placeLocation": {{"latLng": {_deg(*place)}}}}}}}}}'
                )
                counts["visit"] += 1
                if i + 1 == len(plan.stays):
                    continue
                a0, a1 = s1, plan.stays[i + 1][0]
                dest = plan.stays[i + 1][2]
                meters = 111_000 * math.dist(place, dest)
                mode = "IN_PASSENGER_VEHICLE" if meters > 2000 or trip else "WALKING"
                emit_seg(
                    "{" + times(a0, a1) + f', "activity": {{"start": {{"latLng": {_deg(*place)}}}, '
                    f'"end": {{"latLng": {_deg(*dest)}}}, "distanceMeters": {meters:.1f}, '
                    f'"probability": 0.95, "topCandidate": {{"type": "{mode}", '
                    '"probability": 0.9}}}'
                )
                counts["activity"] += 1
                step = 60 if trip else 120
                points = []
                for t in range(int(a0) + step, int(a1), step):
                    lat, lon = plan.where(t)
                    points.append(
                        f'{{"point": {_deg(lat + rng.gauss(0, 2e-4), lon + rng.gauss(0, 2e-4))}, '
                        f'"time": "{_iso(t)}"}}'
                    )
                emit_seg(
                    f'{{"startTime": "{_iso(a0)}", "endTime": "{_iso(a1)}", '
                    f'"timelinePath": [{",".join(points)}]}}'
                )
                counts["path"] += 1
                counts["path_points"] += len(points)
            if plan.nested:
                n0, n1, place = plan.nested
                emit_seg(
                    "{"
                    + times(n0, n1)
                    + ', "visit": {"hierarchyLevel": 1, "probability": 0.7, "topCandidate": '
                    '{"placeId": "ChIJsyntheticLunch", "semanticType": "UNKNOWN", '
                    f'"probability": 0.6, "placeLocation": {{"latLng": {_deg(*place)}}}}}}}}}'
                )
                counts["visit"] += 1
            if trip and trip[0] == HOME:
                emit_seg(
                    "{" + times(start, start + 4 * 86400) + ', "timelineMemory": {"trip": '
                    '{"distanceFromOriginKms": 300, "destinations": '
                    '[{"identifier": {"placeId": "ChIJsyntheticTrip"}}]}}}'
                )
                counts["memory"] += 1

            for t in range(int(start) + 6 * 3600, int(start) + 22 * 3600, RAW_EVERY_S):
                lat, lon = plan.where(t)
                emit_raw(
                    f'{{"position": {{"LatLng": '
                    f"{_deg(lat + rng.gauss(0, 1e-4), lon + rng.gauss(0, 1e-4))}, "
                    f'"accuracyMeters": {rng.randint(3, 40)}, "altitudeMeters": '
                    f'{400 + rng.uniform(-5, 5):.1f}, "source": "GPS", "timestamp": "{_iso(t)}", '
                    f'"speedMetersPerSecond": {rng.uniform(0, 30):.2f}}}}}'
                )
                counts["raw_positions"] += 1
                if t % SCAN_EVERY_S == 0:
                    devices = ",".join(
                        f'{{"mac": {mac_base + rng.randrange(5000)}, '
                        f'"rawRssi": {rng.randint(-95, -40)}}}'
                        for _ in range(8)
                    )
                    emit_raw(
                        f'{{"wifiScan": {{"deliveryTime": "{_iso(t)}", '
                        f'"devicesRecords": [{devices}]}}}}'
                    )
                    emit_raw(
                        f'{{"activityRecord": {{"probableActivities": [{{"type": "STILL", '
                        f'"confidence": {rng.randint(40, 99)}}}, {{"type": "IN_VEHICLE", '
                        f'"confidence": {rng.randint(1, 40)}}}], "timestamp": "{_iso(t)}"}}}}'
                    )
                    counts["other_signals"] += 2
            day += 1
        counts["days"] = day
        seg.write('], "rawSignals": [')

    with side.open("rb") as src, path.open("ab") as dst:
        shutil.copyfileobj(src, dst, 16 << 20)
        dst.write(
            b'], "userLocationProfile": {"frequentPlaces": ['
            + f'{{"placeId": "ChIJsyntheticHome", "placeLocation": {_deg(*HOME)}, '
            f'"label": "HOME"}}, {{"placeId": "ChIJsyntheticWork", "placeLocation": '
            f'{_deg(*WORK)}, "label": "WORK"}}'.encode()
            + b"]}}"
        )
    side.unlink()
    counts["bytes"] = path.stat().st_size
    counts["first_day"] = FIRST_DAY.date().isoformat()
    path.with_suffix(".manifest.json").write_text(json.dumps(counts, indent=1))
    return counts


# --- run --------------------------------------------------------------------------------------


def _django():
    sys.path.insert(0, "/app")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()


def _sizes() -> dict:
    from django.db import connection

    out = {}
    with connection.cursor() as cursor:
        for table in HISTORY_TABLES:
            cursor.execute(
                "SELECT pg_relation_size(%s), pg_indexes_size(%s), pg_total_relation_size(%s)",
                [table, table, table],
            )
            heap, idx, total = cursor.fetchone()
            out[table] = {"heap": heap, "indexes": idx, "total": total}
        cursor.execute("SELECT pg_database_size(current_database())")
        out["database"] = cursor.fetchone()[0]
    return out


def _user():
    from django.utils import timezone

    from travel.accounts.models import User

    user, _ = User.objects.get_or_create(
        email=SCALE_EMAIL,
        defaults={"display_name": "Scale Test (synthetic)"},
    )
    User.objects.filter(pk=user.pk).update(
        privacy_notice_ack_at=timezone.now(), onboarding_done_at=timezone.now(), is_active=True
    )
    user.refresh_from_db()
    return user


class _Client:
    """Plain HTTP to the dev `web` service with a session minted for the throwaway user."""

    def __init__(self, user):
        from django.conf import settings
        from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
        from django.contrib.sessions.backends.db import SessionStore

        store = SessionStore()
        store[SESSION_KEY] = str(user.pk)
        store[BACKEND_SESSION_KEY] = settings.AUTHENTICATION_BACKENDS[0]
        store[HASH_SESSION_KEY] = user.get_session_auth_hash()
        store.create()
        self.csrf = secrets.token_hex(16)  # 32 characters, a valid unmasked token
        self.cookie = f"sessionid={store.session_key}; csrftoken={self.csrf}"
        self.host = os.environ.get("SCALE_WEB", "web:8000")

    def request(self, method: str, path: str, body: bytes | None = None, headers=None):
        conn = http.client.HTTPConnection(self.host, timeout=600)
        all_headers = {
            "Host": "localhost",
            "Cookie": self.cookie,
            "X-CSRFToken": self.csrf,
            "Accept-Encoding": "identity",
            **(headers or {}),
        }
        started = time.perf_counter()
        conn.request(method, path, body=body, headers=all_headers)
        response = conn.getresponse()
        data = response.read()
        elapsed = time.perf_counter() - started
        conn.close()
        return response.status, dict(response.getheaders()), data, elapsed

    def json(self, method: str, path: str, payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        status, _, data, _ = self.request(
            method, path, body, {"Content-Type": "application/json"} if body else None
        )
        if status >= 300:
            raise RuntimeError(f"{method} {path}: {status} {data[:300]!r}")
        return json.loads(data) if data else None


def _tile_xy(lat: float, lon: float, z: int) -> tuple[int, int]:
    n = 2**z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def _time_tiles(client: _Client, first_day: str) -> dict:
    out = {}
    year = int(first_day[:4]) + 1
    ranges = {"all": "", "one_year": f"?from={year}-01-01T00:00:00Z&to={year + 1}-01-01T00:00:00Z"}
    for layer, prefix, zooms in [
        ("points", "/api/v1/history/tiles", TILE_ZOOMS),
        ("segments", "/api/v1/history/segments/tiles", [6, 10, 16]),
    ]:
        for label, query in ranges.items():
            for z in zooms:
                x, y = _tile_xy(*HOME, z)
                runs = []
                for _ in range(3):  # first (cold-ish) and two warm
                    status, headers, data, elapsed = client.request(
                        "GET", f"{prefix}/{z}/{x}/{y}.mvt{query}"
                    )
                    runs.append(round(elapsed * 1000, 1))
                out[f"{layer} {label} z{z}"] = {
                    "status": status,
                    "ms": runs,
                    "bytes": len(data),
                    "aggregated": headers.get("X-Tile-Aggregated"),
                    "truncated": headers.get("X-Tile-Truncated"),
                }
    status, _, data, elapsed = client.request(
        "GET", f"/api/v1/history/coverage?from={year}-01-01&to={year}-12-31&tz=America/Chicago"
    )
    days = len(json.loads(data)["days"]) if status == 200 else None
    out["coverage one year"] = {"status": status, "ms": round(elapsed * 1000, 1), "days": days}
    return out


def run(path: Path, results_path: Path) -> int:
    _django()
    from django.db import connection

    from travel.history.models import ImportBatch

    manifest = json.loads(path.with_suffix(".manifest.json").read_text())
    results: dict = {"generated": manifest, "stages": {}}
    results["sizes_before"] = _sizes()
    user = _user()
    results["user_id"] = user.pk
    client = _Client(user)
    size = path.stat().st_size

    started = time.perf_counter()
    info = client.json(
        "POST",
        "/api/v1/uploads",
        {"filename": "Timeline.json", "size": size, "kind": "google_timeline"},
    )
    chunk = info["chunk_size"]
    with path.open("rb") as handle:
        index = 0
        while data := handle.read(chunk):
            status, _, body, _ = client.request(
                "PUT",
                f"/api/v1/uploads/{info['id']}/chunks/{index}",
                data,
                {
                    "Content-Type": "application/octet-stream",
                    "X-Chunk-SHA256": hashlib.sha256(data).hexdigest(),
                },
            )
            if status != 200:
                raise RuntimeError(f"chunk {index}: {status} {body[:300]!r}")
            index += 1
    batch_id = client.json("POST", f"/api/v1/uploads/{info['id']}/complete")["id"]
    results["stages"]["upload_s"] = round(time.perf_counter() - started, 1)
    results["chunks"] = index
    print(f"uploaded {size / 2**20:.0f} MiB in {index} chunks; batch {batch_id}", flush=True)

    deadline = time.time() + 4 * 3600
    while True:
        batch = ImportBatch.objects.select_related("raw_file").get(pk=batch_id)
        if batch.status not in (ImportBatch.Status.QUEUED, ImportBatch.Status.PROCESSING):
            break
        if time.time() > deadline:
            raise RuntimeError("import did not finish within 4 h")
        time.sleep(2)
    results["status"] = batch.status
    results["error"] = batch.error
    queued = (batch.started_at - batch.created_at).total_seconds() if batch.started_at else None
    results["stages"]["queue_wait_s"] = round(queued, 1) if queued is not None else None
    if batch.raw_file_id and batch.started_at:
        raw = batch.raw_file
        results["stages"]["archive_s"] = round(
            (raw.uploaded_at - batch.started_at).total_seconds(), 1
        )
        results["stages"]["import_s"] = round(
            (batch.finished_at - raw.uploaded_at).total_seconds(), 1
        )
        results["raw_file"] = {"size": raw.size_bytes, "compressed": raw.compressed_size}
    results["summary"] = {k: v for k, v in batch.summary.items() if k != "warnings"}
    print(f"import {batch.status}: {json.dumps(results['stages'])}", flush=True)
    if batch.status != ImportBatch.Status.DONE:
        results_path.write_text(json.dumps(results, indent=1, default=str))
        return 1

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT source, count(*) FROM history_locationpoint WHERE owner_id = %s GROUP BY 1",
            [user.pk],
        )
        results["db_points"] = dict(cursor.fetchall())
        cursor.execute(
            "SELECT kind, count(*) FROM history_timelinesegment WHERE owner_id = %s GROUP BY 1",
            [user.pk],
        )
        results["db_segments"] = dict(cursor.fetchall())
    results["sizes_after_import"] = _sizes()
    with connection.cursor() as cursor:
        # A real import gets the same from autovacuum shortly after; tile plans need the stats.
        cursor.execute("ANALYZE history_locationpoint")
        cursor.execute("ANALYZE history_timelinesegment")
    results["tiles"] = _time_tiles(client, manifest["first_day"])

    expected = {
        "google_raw": manifest["raw_positions"],
        "google_path": manifest["path_points"],
    }
    seg_expected = {k: manifest[k] for k in ("visit", "activity", "path", "memory")}
    results["counts_match"] = (
        results["db_points"] == expected and results["db_segments"] == seg_expected
    )
    results_path.write_text(json.dumps(results, indent=1, default=str))
    print(f"counts match: {results['counts_match']}", flush=True)
    return 0 if results["counts_match"] else 2


# --- cleanup ----------------------------------------------------------------------------------


def cleanup() -> int:
    _django()
    from django.conf import settings
    from django.db import connection

    from travel.accounts.models import User

    user = User.objects.filter(email=SCALE_EMAIL).first()
    if user is None:
        print("cleanup: no scale-test user")
    else:
        uid = user.pk
        with connection.cursor() as cursor:
            # The raw-file trigger blocks UPDATEs only; the owner role may delete.
            for sql in [
                "DELETE FROM history_locationpoint WHERE owner_id = %s",
                "UPDATE history_timelinesegment SET superseded_by_id = NULL WHERE owner_id = %s"
                " AND superseded_by_id IS NOT NULL",
                "DELETE FROM history_timelinesegment WHERE owner_id = %s",
                "DELETE FROM history_placehint WHERE owner_id = %s",
                "DELETE FROM history_coveragereport WHERE owner_id = %s",
                "DELETE FROM history_detectionrun WHERE owner_id = %s",
                "DELETE FROM history_uploadsession WHERE owner_id = %s",
                "DELETE FROM history_importbatch WHERE owner_id = %s",
                "DELETE FROM history_rawfile WHERE owner_id = %s",
            ]:
                cursor.execute(sql, [uid])
                print(f"cleanup: {cursor.rowcount:>9} rows  {sql.split(' WHERE')[0]}")
            cursor.execute(
                "DELETE FROM procrastinate_jobs WHERE task_name = 'history.process_upload'"
                " AND (args->>'owner_id')::int = %s AND status IN ('succeeded', 'failed')",
                [uid],
            )
        from django.contrib.sessions.models import Session

        stale = [
            s.pk for s in Session.objects.all() if s.get_decoded().get("_auth_user_id") == str(uid)
        ]
        Session.objects.filter(pk__in=stale).delete()
        user.delete()
        for sub in ("raw", "uploads"):
            target = Path(settings.BULK_DIR) / sub / str(uid)
            if target.exists():
                for item in target.rglob("*"):
                    if item.is_file():
                        item.chmod(0o640)
                shutil.rmtree(target)
                print(f"cleanup: removed {target}")
        with connection.cursor() as cursor:
            # Return the space to the filesystem (short exclusive locks on a small table).
            cursor.execute("VACUUM FULL history_locationpoint")
            cursor.execute("VACUUM FULL history_timelinesegment")
            cursor.execute("VACUUM ANALYZE history_locationpoint")
            cursor.execute("VACUUM ANALYZE history_timelinesegment")
    scale_dir = Path(settings.BULK_DIR) / "scale-test"
    if scale_dir.exists():
        shutil.rmtree(scale_dir)
        print(f"cleanup: removed {scale_dir}")
    print(f"cleanup: database now {_sizes()['database'] / 2**20:.0f} MiB")
    return 0


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "help"
    if command == "generate":
        path, size_mb = Path(argv[1]), int(argv[2])
        path.parent.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        counts = generate(path, size_mb)
        counts["generate_s"] = round(time.perf_counter() - started, 1)
        path.with_suffix(".manifest.json").write_text(json.dumps(counts, indent=1))
        print(json.dumps(counts))
        return 0
    if command == "run":
        return run(Path(argv[1]), Path(argv[2]))
    if command == "cleanup":
        return cleanup()
    print(__doc__)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
