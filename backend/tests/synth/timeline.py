"""Synthetic Google Timeline exports (SYNTHETIC: generic public city centres, no real history).

Builds the Android structure and converts it to the iOS structure, following the format notes
in docs/research/formats-trackers-datasets.md."""

from __future__ import annotations

import copy
import datetime as dt
import json

CENTRAL = dt.timezone(dt.timedelta(hours=-5))  # a fixed offset is enough for synthetic data

WICHITA = (37.6872, -97.3301)
SALINA = (38.8403, -97.6114)
KANSAS_CITY = (39.0997, -94.5786)
DENVER = (39.7392, -104.9903)


def t(day: int, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2025, 3, day, hour, minute, tzinfo=CENTRAL)


def _iso(when: dt.datetime) -> str:
    return when.isoformat(timespec="milliseconds")


def _deg(lat: float, lon: float) -> str:
    return f"{lat:.7f}°, {lon:.7f}°"


def visit(start, end, where, place_id="ChIJsyntheticPlace", semantic="UNKNOWN", level=0, prob=0.9):
    return {
        "startTime": _iso(start),
        "endTime": _iso(end),
        "startTimeTimezoneUtcOffsetMinutes": -300,
        "endTimeTimezoneUtcOffsetMinutes": -300,
        "visit": {
            "hierarchyLevel": level,
            "probability": prob,
            "topCandidate": {
                "placeId": place_id,
                "semanticType": semantic,
                "probability": prob,
                "placeLocation": {"latLng": _deg(*where)},
            },
        },
    }


def activity(start, end, origin, destination, kind="IN_PASSENGER_VEHICLE", meters=100_000.0):
    return {
        "startTime": _iso(start),
        "endTime": _iso(end),
        "startTimeTimezoneUtcOffsetMinutes": -300,
        "endTimeTimezoneUtcOffsetMinutes": -300,
        "activity": {
            "start": {"latLng": _deg(*origin)},
            "end": {"latLng": _deg(*destination)},
            "distanceMeters": meters,
            "probability": 0.95,
            "topCandidate": {"type": kind, "probability": 0.9},
        },
    }


def path(start, end, points):
    """points: [(lat, lon, datetime)]"""
    return {
        "startTime": _iso(start),
        "endTime": _iso(end),
        "timelinePath": [
            {"point": _deg(lat, lon), "time": _iso(when)} for lat, lon, when in points
        ],
    }


def memory(start, end, destinations):
    return {
        "startTime": _iso(start),
        "endTime": _iso(end),
        "startTimeTimezoneUtcOffsetMinutes": -300,
        "endTimeTimezoneUtcOffsetMinutes": -300,
        "timelineMemory": {
            "trip": {
                "distanceFromOriginKms": 300,
                "destinations": [{"identifier": {"placeId": d}} for d in destinations],
            }
        },
    }


def raw_position(when, where, accuracy=10, speed=None):
    position = {
        "LatLng": _deg(*where),
        "accuracyMeters": accuracy,
        "altitudeMeters": 400.0,
        "source": "GPS",
        "timestamp": _iso(when),
    }
    if speed is not None:
        position["speedMetersPerSecond"] = speed
    return {"position": position}


def android_export(segments, raw_signals=(), frequent_places=()) -> dict:
    return {
        "semanticSegments": list(segments),
        "rawSignals": [*raw_signals, {"wifiScan": {"deliveryTime": "x", "devicesRecords": []}}],
        "userLocationProfile": {"frequentPlaces": list(frequent_places)},
    }


def frequent_place(where, label="HOME", place_id="ChIJsyntheticHome"):
    return {"placeId": place_id, "placeLocation": _deg(*where), "label": label}


def road_trip() -> dict:
    """Home in Wichita, drive to Kansas City via Salina, a night away, drive back."""
    return android_export(
        [
            visit(t(1, 0), t(1, 8), WICHITA, "ChIJsyntheticHome", "INFERRED_HOME"),
            activity(t(1, 8), t(1, 10), WICHITA, SALINA, meters=150_000),
            visit(t(1, 10), t(1, 11), SALINA, "ChIJsyntheticSalina"),
            activity(t(1, 11), t(1, 14), SALINA, KANSAS_CITY, meters=290_000),
            visit(t(1, 14), t(2, 9), KANSAS_CITY, "ChIJsyntheticHotel"),
            visit(t(1, 15), t(1, 16), KANSAS_CITY, "ChIJsyntheticMuseum", level=1),
            activity(t(2, 9), t(2, 12), KANSAS_CITY, WICHITA, meters=320_000),
            visit(t(2, 12), t(3, 8), WICHITA, "ChIJsyntheticHome", "HOME"),
            path(
                t(1, 8),
                t(1, 10),
                [(37.7, -97.4, t(1, 8, 15)), (38.2, -97.5, t(1, 9, 0)), (38.8, -97.6, t(1, 9, 50))],
            ),
            memory(t(1, 8), t(2, 12), ["ChIJsyntheticHotel"]),
        ],
        raw_signals=[
            raw_position(t(1, 8, 30), (37.8, -97.45), speed=27.0),
            raw_position(t(1, 9, 30), (38.5, -97.55), speed=29.0),
        ],
        frequent_places=[frequent_place(WICHITA)],
    )


def to_ios(export: dict) -> list:
    """The iOS variant: a bare array, string numbers, geo: URIs, placeID, human enum spellings,
    minute-offset path points, path records grouped at the end."""
    human = {
        "IN_PASSENGER_VEHICLE": "in passenger vehicle",
        "FLYING": "flying",
        "WALKING": "walking",
        "INFERRED_HOME": "Home",
        "HOME": "Home",
        "UNKNOWN": "Unknown",
        "SEARCHED_ADDRESS": "Searched Address",
    }

    def geo(value: str) -> str:
        lat, lon = (float(part.strip().rstrip("°")) for part in value.split(","))
        return f"geo:{lat:.6f},{lon:.6f}"

    def zulu(text: str) -> str:
        return (
            dt.datetime.fromisoformat(text)
            .astimezone(dt.UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )

    items, paths = [], []
    for segment in copy.deepcopy(export["semanticSegments"]):
        out = {"startTime": zulu(segment["startTime"]), "endTime": zulu(segment["endTime"])}
        if "visit" in segment:
            v, top = segment["visit"], segment["visit"]["topCandidate"]
            out["visit"] = {
                "hierarchyLevel": str(v["hierarchyLevel"]),
                "probability": f"{v['probability']:.6f}",
                "isTimelessVisit": "false",
                "topCandidate": {
                    "placeID": top["placeId"],
                    "semanticType": human.get(top["semanticType"], "Unknown"),
                    "probability": f"{top['probability']:.6f}",
                    "placeLocation": geo(top["placeLocation"]["latLng"]),
                },
            }
            items.append(out)
        elif "activity" in segment:
            a = segment["activity"]
            out["activity"] = {
                "start": geo(a["start"]["latLng"]),
                "end": geo(a["end"]["latLng"]),
                "distanceMeters": f"{a['distanceMeters']:.6f}",
                "topCandidate": {
                    "type": human.get(a["topCandidate"]["type"], "unknown"),
                    "probability": "0.000000",
                },
            }
            items.append(out)
        elif "timelinePath" in segment:
            start = dt.datetime.fromisoformat(segment["startTime"])
            out["timelinePath"] = [
                {
                    "point": geo(p["point"]),
                    "durationMinutesOffsetFromStartTime": str(
                        int((dt.datetime.fromisoformat(p["time"]) - start).total_seconds() // 60)
                    ),
                }
                for p in segment["timelinePath"]
            ]
            paths.append(out)
    return items + paths


def dumps(document) -> bytes:
    """Serialized with a SYNTHETIC marker first, like committed fixtures."""
    if isinstance(document, dict):
        document = {"SYNTHETIC": "generated test data", **document}
    return json.dumps(document).encode()
