from django.db import migrations

# Raw history of their owner (PLAN.md §6.3): only the owner reads or changes them, never the
# Admin; writing needs a role that may import (Viewers have no raw history). The SECURITY
# DEFINER helpers run once per statement (InitPlan), as in history migration 0007.
SQL = """
ALTER TABLE flights_flightrecord ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_all ON flights_flightrecord FOR ALL TO travel_app
  USING (owner_id = app.user_id() AND (SELECT app.is_family()))
  WITH CHECK (owner_id = app.user_id() AND (SELECT app.can_create()));
"""

REVERSE = """
DROP POLICY IF EXISTS own_all ON flights_flightrecord;
ALTER TABLE flights_flightrecord DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [("flights", "0001_initial"), ("core", "0002_row_level_security")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
