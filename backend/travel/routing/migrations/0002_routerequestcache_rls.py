from django.db import migrations

# The proposal cache holds the waypoints a user drew: only that user reads or changes their
# rows, never the Admin; writing needs a role that may create (Viewers don't route).
SQL = """
ALTER TABLE routing_routerequestcache ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_all ON routing_routerequestcache FOR ALL TO travel_app
  USING (owner_id = app.user_id() AND (SELECT app.is_family()))
  WITH CHECK (owner_id = app.user_id() AND (SELECT app.can_create()));
"""

REVERSE = """
DROP POLICY IF EXISTS own_all ON routing_routerequestcache;
ALTER TABLE routing_routerequestcache DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [("routing", "0001_initial"), ("core", "0002_row_level_security")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
