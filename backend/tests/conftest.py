"""Every database test runs as the runtime role `travel_app`, so row-level security and table
privileges apply exactly as in production. The test database itself is created and migrated by
the owner role (pytest-django's setup); fixtures that need to bypass RLS to build data use
`tests.helpers.as_owner()` explicitly."""

import pytest
from django.db import connections


@pytest.fixture(autouse=True)
def _run_db_tests_as_app_role(request):
    marker = request.node.get_closest_marker("django_db")
    if marker is None or request.node.get_closest_marker("as_owner"):
        yield
        return
    request.getfixturevalue("db" if not marker.kwargs.get("transaction") else "transactional_db")
    with connections["default"].cursor() as cursor:
        cursor.execute("SET ROLE travel_app")
    yield
    with connections["default"].cursor() as cursor:
        cursor.execute("RESET ROLE")
