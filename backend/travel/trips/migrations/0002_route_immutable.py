"""Saved routes are frozen (CLAUDE.md rule 5): reject every UPDATE of a route version."""

from django.db import migrations

SQL = """
CREATE FUNCTION trips_route_reject_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'route versions are immutable; insert a new version instead'
    USING ERRCODE = 'restrict_violation';
END $$;

CREATE TRIGGER route_immutable BEFORE UPDATE ON trips_route
FOR EACH ROW EXECUTE FUNCTION trips_route_reject_update();
"""

REVERSE = """
DROP TRIGGER IF EXISTS route_immutable ON trips_route;
DROP FUNCTION IF EXISTS trips_route_reject_update();
"""


class Migration(migrations.Migration):
    dependencies = [("trips", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
