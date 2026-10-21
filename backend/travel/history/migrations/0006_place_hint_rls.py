from django.db import migrations

SQL = """
ALTER TABLE history_placehint ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_all ON history_placehint FOR ALL TO travel_app
  USING (owner_id = app.user_id() AND app.is_family())
  WITH CHECK (owner_id = app.user_id() AND app.is_family());
"""

REVERSE = """
DROP POLICY IF EXISTS own_all ON history_placehint;
ALTER TABLE history_placehint DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [("history", "0005_segment_level_place_hints")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
