"""Fake routing providers for tests (work-order item 25). `fake(answers)` replaces
`requests.get/post` in travel.routing.providers with a recorder that answers with synthetic
payloads and remembers exactly what would have left the server (rule 13)."""

import json

import polyline
import pytest

from travel.routing import providers

# Synthetic points: two inside the Kansas coverage, two outside it.
WICHITA = (-97.3301, 37.6872)
SALINA = (-97.6114, 38.8403)
DENVER = (-104.9903, 39.7392)
OMAHA = (-95.9345, 41.2565)

LINE = [[-97.3301, 37.6872], [-97.5, 38.2], [-97.6114, 38.8403]]


def osrm_answer(engine_line=LINE):
    return {
        "code": "Ok",
        "routes": [
            {
                "geometry": {"type": "LineString", "coordinates": engine_line},
                "distance": 144672.4,
                "duration": 4653.2,
                "weight": 9999,
                "legs": [{"distance": 144672.4, "duration": 4653.2, "summary": "", "steps": []}],
            }
        ],
        "waypoints": [
            {"location": LINE[0], "name": "Synthetic Avenue", "hint": "x"},
            {"location": LINE[-1], "name": "Synthetic Street", "hint": "y"},
        ],
    }


def ors_answer():
    return {
        "routes": [
            {
                "summary": {"distance": 150000.0, "duration": 5000.0},
                "segments": [{"distance": 150000.0, "duration": 5000.0}],
                "geometry": polyline.encode([(lat, lon) for lon, lat in LINE], 5),
                "way_points": [0, 2],
            }
        ],
        "metadata": {"engine": {"version": "9.0.0", "graph_date": "2026-11-01T10:00:00Z"}},
    }


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.content = json.dumps(payload).encode() if payload is not None else b""

    def json(self):
        if self._payload is None:
            raise ValueError("no body")
        return self._payload


class Recorder:
    """Stands in for requests.get/post. `answers` maps a URL substring to a response, an
    exception, or a list of them (consumed in order)."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def _answer(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        for fragment, answer in self.answers.items():
            if fragment in url:
                if isinstance(answer, list):
                    answer = answer.pop(0)
                if isinstance(answer, Exception):
                    raise answer
                return answer
        raise AssertionError(f"unexpected request to {url}")

    def get(self, url, **kwargs):
        return self._answer("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._answer("POST", url, **kwargs)

    def urls(self):
        return [c["url"] for c in self.calls]


@pytest.fixture
def fake(monkeypatch, settings):
    settings.VALHALLA_URL = "http://valhalla:8002"
    settings.VALHALLA_COVERAGE = "kansas"
    settings.VALHALLA_DATA_DATE = ""
    settings.ORS_API_KEY = ""
    settings.ORS_URL = "https://ors.invalid"
    settings.FOSSGIS_OSRM_URL = "https://fossgis.invalid/routed-car"
    settings.ROUTING_FOSSGIS_ENABLED = True
    providers._status_cache.clear()

    def install(answers):
        recorder = Recorder(answers)
        monkeypatch.setattr(providers.requests, "get", recorder.get)
        monkeypatch.setattr(providers.requests, "post", recorder.post)
        return recorder

    return install


STATUS = FakeResponse(200, {"version": "3.9.1", "tileset_last_modified": 1763424000})
