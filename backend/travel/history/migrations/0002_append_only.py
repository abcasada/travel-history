"""Raw data integrity: raw files and location points are never updated; Timeline segment
versions are append-only except for the current-version pointer (PLAN.md §5.5)."""

from django.db import migrations

SQL = """
CREATE FUNCTION history_reject_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% rows are append-only/immutable', TG_TABLE_NAME
    USING ERRCODE = 'restrict_violation';
END $$;

CREATE TRIGGER rawfile_immutable BEFORE UPDATE ON history_rawfile
FOR EACH ROW EXECUTE FUNCTION history_reject_update();

CREATE TRIGGER locationpoint_append_only BEFORE UPDATE ON history_locationpoint
FOR EACH ROW EXECUTE FUNCTION history_reject_update();

-- Only is_current and superseded_by may change on an existing segment version.
-- time_range is a generated column and is excluded from the comparison.
CREATE FUNCTION history_segment_pointer_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF (to_jsonb(NEW) - 'is_current' - 'superseded_by_id' - 'time_range')
     IS DISTINCT FROM
     (to_jsonb(OLD) - 'is_current' - 'superseded_by_id' - 'time_range') THEN
    RAISE EXCEPTION 'timeline segment versions are append-only; only is_current/superseded_by may change'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER segment_append_only BEFORE UPDATE ON history_timelinesegment
FOR EACH ROW EXECUTE FUNCTION history_segment_pointer_only();
"""

REVERSE = """
DROP TRIGGER IF EXISTS segment_append_only ON history_timelinesegment;
DROP FUNCTION IF EXISTS history_segment_pointer_only();
DROP TRIGGER IF EXISTS locationpoint_append_only ON history_locationpoint;
DROP TRIGGER IF EXISTS rawfile_immutable ON history_rawfile;
DROP FUNCTION IF EXISTS history_reject_update();
"""


class Migration(migrations.Migration):
    dependencies = [("history", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
