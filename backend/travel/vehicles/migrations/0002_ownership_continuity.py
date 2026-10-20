"""Exactly one owner at any time (PLAN.md §5.4). The exclusion constraint already forbids
overlaps; these deferred constraint triggers (checked at commit) forbid gaps between periods and
vehicles without any ownership period. SECURITY DEFINER so the check sees every period
regardless of row-level security."""

from django.db import migrations

SQL = """
CREATE FUNCTION vehicles_assert_owned_continuously(vid bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM vehicles_vehicle WHERE id = vid) THEN
    RETURN;  -- vehicle deleted in this transaction
  END IF;
  IF NOT EXISTS (SELECT 1 FROM vehicles_vehicleownership WHERE vehicle_id = vid) THEN
    RAISE EXCEPTION 'vehicle % has no owner', vid USING ERRCODE = 'check_violation';
  END IF;
  IF EXISTS (
    SELECT 1 FROM (
      SELECT valid_from,
             lag(valid_to) OVER w AS prev_to,
             row_number() OVER w AS rn
      FROM vehicles_vehicleownership
      WHERE vehicle_id = vid
      WINDOW w AS (ORDER BY valid_from NULLS FIRST)
    ) periods
    WHERE rn > 1 AND prev_to IS DISTINCT FROM valid_from
  ) THEN
    RAISE EXCEPTION 'vehicle % ownership history has a gap', vid USING ERRCODE = 'check_violation';
  END IF;
END $$;

CREATE FUNCTION vehicles_ownership_changed() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF TG_OP IN ('UPDATE', 'DELETE') THEN
    PERFORM vehicles_assert_owned_continuously(OLD.vehicle_id);
  END IF;
  IF TG_OP IN ('INSERT', 'UPDATE') THEN
    PERFORM vehicles_assert_owned_continuously(NEW.vehicle_id);
  END IF;
  RETURN NULL;
END $$;

CREATE FUNCTION vehicles_vehicle_created() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  PERFORM vehicles_assert_owned_continuously(NEW.id);
  RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER ownership_continuous
AFTER INSERT OR UPDATE OR DELETE ON vehicles_vehicleownership
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION vehicles_ownership_changed();

CREATE CONSTRAINT TRIGGER vehicle_has_owner
AFTER INSERT ON vehicles_vehicle
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION vehicles_vehicle_created();
"""

REVERSE = """
DROP TRIGGER IF EXISTS vehicle_has_owner ON vehicles_vehicle;
DROP TRIGGER IF EXISTS ownership_continuous ON vehicles_vehicleownership;
DROP FUNCTION IF EXISTS vehicles_vehicle_created();
DROP FUNCTION IF EXISTS vehicles_ownership_changed();
DROP FUNCTION IF EXISTS vehicles_assert_owned_continuously(bigint);
"""


class Migration(migrations.Migration):
    dependencies = [("vehicles", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
