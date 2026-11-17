"""Small reference-data subsets for flight tests (tests/fixtures/flights/, SYNTHETIC header)."""

from pathlib import Path

from tests.helpers import as_owner
from travel.geo import flight_reference as ref

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "flights"
SPREADSHEET = FIXTURES / "flights_synthetic.csv"


def load_reference() -> None:
    """Load the subsets as the owner role (the app role may only read `geo_` tables)."""
    with as_owner():
        ref.load_airports(ref.from_local_file(ref.AIRPORTS, FIXTURES / "airports.csv"))
        ref.load_airlines(ref.from_local_file(ref.AIRLINES, FIXTURES / "airlines.dat"))
        ref.load_aircraft(ref.from_local_file(ref.AIRCRAFT, FIXTURES / "planes.dat"))
