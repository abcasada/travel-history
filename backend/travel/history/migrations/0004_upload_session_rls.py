from django.db import migrations

SQL = """
ALTER TABLE history_uploadsession ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_all ON history_uploadsession FOR ALL TO travel_app
  USING (owner_id = app.user_id() AND app.is_family())
  WITH CHECK (owner_id = app.user_id() AND app.can_create());
"""

REVERSE = """
DROP POLICY IF EXISTS own_all ON history_uploadsession;
ALTER TABLE history_uploadsession DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [("history", "0003_upload_session"), ("core", "0002_row_level_security")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
