"""Row-level rules the trips API relies on (work-order item 6, PLAN.md §6.3-§6.4, D-81).

1. People: a core editor may add as a participant, or set a leg override for, only a person
   they can see. Otherwise a guessed id would put a private person's name on a trip that
   others can read (`app.can_view_person` includes "on a trip I can view").
2. Contributed legs: deleting one now needs the same right as editing it (the author, while
   they may still contribute), as in §6.3 and travel.core.policy.can_edit_leg.
3. References (foreign keys bypass row-level security, so these are triggers):
   - a trip's purpose belongs to the trip's owner, and its cover photo belongs to the trip;
   - a leg's stops belong to the leg's trip, and its current route is one of its own versions;
   - a leg gets a vehicle only if the acting user can see it (hidden vehicles stay hidden).
   The reference checks are integrity rules for everyone, so they run with the owner's rights
   (SECURITY DEFINER trigger functions cannot be called directly). The vehicle check depends on
   the caller, so it runs with the caller's rights and exempts the owner role, like the guards
   in core migration 0002. Each check fires only when the column is set or changed, so an
   unchanged reference never blocks an unrelated edit (or a transfer).
"""

from django.db import migrations

FORWARD = r"""
ALTER POLICY participant_insert ON trips_tripparticipant
  WITH CHECK (app.can_edit_trip_core(trip_id) AND added_by_id = app.user_id()
              AND app.can_view_person(person_id));
ALTER POLICY participant_update ON trips_tripparticipant
  USING (app.can_edit_trip_core(trip_id)
         OR (app.manages_person(person_id) AND app.can_view_trip(trip_id)))
  WITH CHECK ((app.can_edit_trip_core(trip_id)
               OR (app.manages_person(person_id) AND app.can_view_trip(trip_id)))
              AND app.can_view_person(person_id));

ALTER POLICY legoverride_write ON trips_legparticipantoverride
  USING (app.can_edit_trip_core(app.leg_trip(leg_id))
         OR (app.manages_person(person_id) AND app.can_contribute(app.leg_trip(leg_id))))
  WITH CHECK (set_by_id = app.user_id() AND app.can_view_person(person_id) AND (
    app.can_edit_trip_core(app.leg_trip(leg_id))
    OR (app.manages_person(person_id) AND app.can_contribute(app.leg_trip(leg_id)))));

ALTER POLICY leg_delete ON trips_leg
  USING ((NOT is_contribution AND app.can_edit_trip_core(trip_id))
         OR (is_contribution AND author_id = app.user_id() AND app.can_contribute(trip_id)));

CREATE FUNCTION app.guard_trip_refs() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF NEW.purpose_id IS NOT NULL
     AND (TG_OP = 'INSERT' OR NEW.purpose_id IS DISTINCT FROM OLD.purpose_id)
     AND (SELECT owner_id FROM trips_purpose WHERE id = NEW.purpose_id)
         IS DISTINCT FROM NEW.owner_id THEN
    RAISE EXCEPTION 'a trip takes only its owner''s purposes' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.cover_media_id IS NOT NULL
     AND (TG_OP = 'INSERT' OR NEW.cover_media_id IS DISTINCT FROM OLD.cover_media_id)
     AND (SELECT trip_id FROM media_media WHERE id = NEW.cover_media_id)
         IS DISTINCT FROM NEW.id THEN
    RAISE EXCEPTION 'a trip''s cover must be one of its own photos'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trip_refs_guard BEFORE INSERT OR UPDATE OF purpose_id, cover_media_id
ON trips_trip FOR EACH ROW EXECUTE FUNCTION app.guard_trip_refs();

CREATE FUNCTION app.guard_leg_refs() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF NEW.origin_stop_id IS NOT NULL
     AND (TG_OP = 'INSERT' OR NEW.origin_stop_id IS DISTINCT FROM OLD.origin_stop_id)
     AND (SELECT trip_id FROM trips_stop WHERE id = NEW.origin_stop_id)
         IS DISTINCT FROM NEW.trip_id THEN
    RAISE EXCEPTION 'a leg''s stops belong to its own trip' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.destination_stop_id IS NOT NULL
     AND (TG_OP = 'INSERT' OR NEW.destination_stop_id IS DISTINCT FROM OLD.destination_stop_id)
     AND (SELECT trip_id FROM trips_stop WHERE id = NEW.destination_stop_id)
         IS DISTINCT FROM NEW.trip_id THEN
    RAISE EXCEPTION 'a leg''s stops belong to its own trip' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.current_route_id IS NOT NULL
     AND (TG_OP = 'INSERT' OR NEW.current_route_id IS DISTINCT FROM OLD.current_route_id)
     AND (SELECT leg_id FROM trips_route WHERE id = NEW.current_route_id)
         IS DISTINCT FROM NEW.id THEN
    RAISE EXCEPTION 'a leg''s current route must be one of its own versions'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER leg_refs_guard
BEFORE INSERT OR UPDATE OF origin_stop_id, destination_stop_id, current_route_id
ON trips_leg FOR EACH ROW EXECUTE FUNCTION app.guard_leg_refs();

CREATE FUNCTION app.guard_leg_vehicle() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
  IF current_user <> 'travel_owner' AND NEW.vehicle_id IS NOT NULL
     AND (TG_OP = 'INSERT' OR NEW.vehicle_id IS DISTINCT FROM OLD.vehicle_id)
     AND NOT app.can_view_vehicle(NEW.vehicle_id) THEN
    RAISE EXCEPTION 'cannot use a vehicle you cannot see' USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER leg_vehicle_guard BEFORE INSERT OR UPDATE OF vehicle_id
ON trips_leg FOR EACH ROW EXECUTE FUNCTION app.guard_leg_vehicle();
"""

REVERSE = r"""
DROP TRIGGER leg_vehicle_guard ON trips_leg;
DROP FUNCTION app.guard_leg_vehicle();
DROP TRIGGER leg_refs_guard ON trips_leg;
DROP FUNCTION app.guard_leg_refs();
DROP TRIGGER trip_refs_guard ON trips_trip;
DROP FUNCTION app.guard_trip_refs();

ALTER POLICY leg_delete ON trips_leg
  USING ((NOT is_contribution AND app.can_edit_trip_core(trip_id))
         OR (is_contribution AND author_id = app.user_id()));
ALTER POLICY legoverride_write ON trips_legparticipantoverride
  USING (app.can_edit_trip_core(app.leg_trip(leg_id))
         OR (app.manages_person(person_id) AND app.can_contribute(app.leg_trip(leg_id))))
  WITH CHECK (set_by_id = app.user_id() AND (
    app.can_edit_trip_core(app.leg_trip(leg_id))
    OR (app.manages_person(person_id) AND app.can_contribute(app.leg_trip(leg_id)))));
ALTER POLICY participant_update ON trips_tripparticipant
  USING (app.can_edit_trip_core(trip_id)
         OR (app.manages_person(person_id) AND app.can_view_trip(trip_id)))
  WITH CHECK (app.can_edit_trip_core(trip_id)
              OR (app.manages_person(person_id) AND app.can_view_trip(trip_id)));
ALTER POLICY participant_insert ON trips_tripparticipant
  WITH CHECK (app.can_edit_trip_core(trip_id) AND added_by_id = app.user_id());
"""


class Migration(migrations.Migration):
    dependencies = [
        ("trips", "0002_route_immutable"),
        ("core", "0002_row_level_security"),
        ("accounts", "0003_user_directory"),
    ]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
