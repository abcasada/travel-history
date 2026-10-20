"""Basic photos per contributor per trip are capped by trip.photo_limit_per_contributor
(PLAN.md §16.1). Enforced in the app too; this is the backstop. An advisory lock serializes
concurrent uploads by the same contributor to the same trip."""

from django.db import migrations

SQL = """
CREATE FUNCTION media_enforce_photo_limit() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  lim integer;
  n integer;
BEGIN
  IF NEW.trip_id IS NULL OR NEW.source <> 'local' THEN
    RETURN NEW;
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('media_limit:' || NEW.trip_id || ':' || NEW.author_id, 0));
  SELECT photo_limit_per_contributor INTO lim FROM trips_trip WHERE id = NEW.trip_id;
  SELECT count(*) INTO n FROM media_media
   WHERE trip_id = NEW.trip_id AND author_id = NEW.author_id AND source = 'local';
  IF n >= lim THEN
    RAISE EXCEPTION 'photo limit of % per contributor reached for trip %', lim, NEW.trip_id
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER media_photo_limit BEFORE INSERT ON media_media
FOR EACH ROW EXECUTE FUNCTION media_enforce_photo_limit();
"""

REVERSE = """
DROP TRIGGER IF EXISTS media_photo_limit ON media_media;
DROP FUNCTION IF EXISTS media_enforce_photo_limit();
"""


class Migration(migrations.Migration):
    dependencies = [("media", "0002_initial"), ("trips", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
