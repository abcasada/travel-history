"""Row-level rules for the rest of the trips API (work-order item 13, PLAN.md §6.3-§6.4, D-89).

1. Contributions (notes, GPS tracks, own tags on a trip, trip photos) follow the leg rule from
   item 6: their author edits and deletes them only while they may still contribute to the trip.
   A participant who was removed keeps read access to a family trip, but no longer changes what
   they left on it.
2. Q-16 (answered by Adam 2026-11-17): the trip owner may delete a contribution (a leg, note,
   track, tag or photo) whose author is no longer on the trip. "On the trip" is the same test as
   for sharing (a trip-level participant or on a leg by an include override); the owner's own
   rows are never "left". So at any time someone may delete a contribution: its author while
   they are on the trip, otherwise the trip owner.
3. References that foreign keys check without row-level security (triggers, like trips 0003):
   - a stop's leg belongs to the stop's trip; a photo's leg and stop belong to the photo's trip
     (integrity rules for every role);
   - a stop's place is one the acting user owns, or one already used by another stop of the same
     trip. Otherwise a guessed place id (places can be home addresses) would put someone's
     private place on a trip the guesser can read. The owner role is exempt (imports).
4. Leg order: `app.reorder_legs(trip, leg_ids)` lets a core editor renumber every leg of a trip,
   contributed legs included. Contributed legs are otherwise only their author's to change, so
   this runs with the owner's rights and changes nothing but `sequence` (and `updated_at`).
"""

from django.db import migrations

FORWARD = r"""
-- Another account's person (the directory shows it to the family anyway, D-76).
CREATE FUNCTION app.user_person(u bigint) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT person_id FROM accounts_user WHERE id = u AND app.is_family()
$$;

-- Person p is on trip t: trip-level, or added to any leg (as app.is_trip_participant, for any
-- person). Only answers for trips the caller can see.
CREATE FUNCTION app.is_person_on_trip(t bigint, p bigint) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT p IS NOT NULL AND app.can_view_trip(t) AND (
    EXISTS (SELECT 1 FROM trips_tripparticipant WHERE trip_id = t AND person_id = p)
    OR EXISTS (SELECT 1 FROM trips_legparticipantoverride o
                 JOIN trips_leg l ON l.id = o.leg_id
                WHERE l.trip_id = t AND o.person_id = p AND o.include))
$$;

-- Q-16: the trip owner may delete what an author who is no longer on the trip left on it.
CREATE FUNCTION app.can_delete_left_contribution(t bigint, author bigint) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT app.is_family() AND app.trip_owner(t) = app.user_id()
     AND author IS DISTINCT FROM app.user_id()
     AND NOT coalesce(app.is_person_on_trip(t, app.user_person(author)), false)
$$;

ALTER POLICY leg_delete ON trips_leg
  USING ((NOT is_contribution AND app.can_edit_trip_core(trip_id))
         OR (is_contribution AND author_id = app.user_id() AND app.can_contribute(trip_id))
         OR (is_contribution AND app.can_delete_left_contribution(trip_id, author_id)));

ALTER POLICY note_update ON trips_tripnote
  USING (author_id = app.user_id() AND app.can_contribute(trip_id))
  WITH CHECK (author_id = app.user_id() AND app.can_contribute(trip_id));
ALTER POLICY note_delete ON trips_tripnote
  USING ((author_id = app.user_id() AND app.can_contribute(trip_id))
         OR app.can_delete_left_contribution(trip_id, author_id));

ALTER POLICY track_update ON trips_trackcontribution
  USING (author_id = app.user_id() AND app.can_contribute(trip_id))
  WITH CHECK (author_id = app.user_id() AND app.can_contribute(trip_id));
ALTER POLICY track_delete ON trips_trackcontribution
  USING ((author_id = app.user_id() AND app.can_contribute(trip_id))
         OR app.can_delete_left_contribution(trip_id, author_id));

ALTER POLICY triptag_delete ON trips_triptag
  USING ((author_id = app.user_id() AND app.can_contribute(trip_id))
         OR app.can_delete_left_contribution(trip_id, author_id));

-- Trip photos follow the contribution rule; vehicle photos and avatars keep their rules. The
-- update check now also stops an author from moving a photo onto a trip they can't contribute to.
ALTER POLICY media_update ON media_media
  USING (author_id = app.user_id() AND CASE
    WHEN trip_id IS NOT NULL THEN app.can_contribute(trip_id)
    ELSE app.media_visible(trip_id, vehicle_id, author_id) END)
  WITH CHECK (author_id = app.user_id() AND CASE
    WHEN trip_id IS NOT NULL THEN app.can_contribute(trip_id)
    ELSE true END);
ALTER POLICY media_delete ON media_media
  USING ((author_id = app.user_id() AND CASE
            WHEN trip_id IS NOT NULL THEN app.can_contribute(trip_id)
            ELSE app.is_family() END)
         OR (trip_id IS NOT NULL AND app.can_delete_left_contribution(trip_id, author_id)));

-- A place the acting user may put on a stop of trip t: their own, or one already on that trip.
CREATE FUNCTION app.can_use_place(pl bigint, t bigint) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT app.is_family() AND app.can_view_trip(t) AND EXISTS (
    SELECT 1 FROM trips_place p WHERE p.id = pl AND (
      p.owner_id = app.user_id()
      OR EXISTS (SELECT 1 FROM trips_stop s WHERE s.place_id = p.id AND s.trip_id = t)))
$$;

CREATE FUNCTION app.guard_stop_place() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
  IF current_user <> 'travel_owner'
     AND (TG_OP = 'INSERT'
          OR (NEW.place_id, NEW.trip_id) IS DISTINCT FROM (OLD.place_id, OLD.trip_id))
     AND NOT app.can_use_place(NEW.place_id, NEW.trip_id) THEN
    RAISE EXCEPTION 'cannot use a place you cannot see' USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER stop_place_guard BEFORE INSERT OR UPDATE OF place_id, trip_id
ON trips_stop FOR EACH ROW EXECUTE FUNCTION app.guard_stop_place();

CREATE FUNCTION app.guard_stop_refs() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF NEW.leg_id IS NOT NULL
     AND (TG_OP = 'INSERT' OR (NEW.leg_id, NEW.trip_id) IS DISTINCT FROM (OLD.leg_id, OLD.trip_id))
     AND (SELECT trip_id FROM trips_leg WHERE id = NEW.leg_id) IS DISTINCT FROM NEW.trip_id THEN
    RAISE EXCEPTION 'a stop''s leg belongs to its own trip' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER stop_refs_guard BEFORE INSERT OR UPDATE OF leg_id, trip_id
ON trips_stop FOR EACH ROW EXECUTE FUNCTION app.guard_stop_refs();

CREATE FUNCTION app.guard_media_refs() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF NEW.leg_id IS NOT NULL
     AND (TG_OP = 'INSERT' OR (NEW.leg_id, NEW.trip_id) IS DISTINCT FROM (OLD.leg_id, OLD.trip_id))
     AND (NEW.trip_id IS NULL
          OR (SELECT trip_id FROM trips_leg WHERE id = NEW.leg_id) IS DISTINCT FROM NEW.trip_id) THEN
    RAISE EXCEPTION 'a photo''s leg belongs to its own trip' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.stop_id IS NOT NULL
     AND (TG_OP = 'INSERT' OR (NEW.stop_id, NEW.trip_id) IS DISTINCT FROM (OLD.stop_id, OLD.trip_id))
     AND (NEW.trip_id IS NULL
          OR (SELECT trip_id FROM trips_stop WHERE id = NEW.stop_id) IS DISTINCT FROM NEW.trip_id) THEN
    RAISE EXCEPTION 'a photo''s stop belongs to its own trip' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER media_refs_guard BEFORE INSERT OR UPDATE OF leg_id, stop_id, trip_id
ON media_media FOR EACH ROW EXECUTE FUNCTION app.guard_media_refs();

-- Renumber every leg of trip t in the order given (core editors only). Same advisory lock as
-- leg creation (travel.trips.services._next_sequence), so a concurrent new leg can't collide.
CREATE FUNCTION app.reorder_legs(t bigint, leg_ids bigint[]) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF NOT app.can_edit_trip_core(t) THEN
    RAISE EXCEPTION 'only the trip''s core editors reorder its legs'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('trips_leg.sequence:' || t, 0));
  IF (SELECT coalesce(array_agg(id ORDER BY id), '{}') FROM trips_leg WHERE trip_id = t)
     IS DISTINCT FROM
     (SELECT coalesce(array_agg(x ORDER BY x), '{}') FROM unnest(leg_ids) AS u(x)) THEN
    RAISE EXCEPTION 'list every leg of the trip exactly once' USING ERRCODE = 'check_violation';
  END IF;
  UPDATE trips_leg l SET sequence = o.n, updated_at = now()
    FROM unnest(leg_ids) WITH ORDINALITY AS o(id, n)
   WHERE l.id = o.id AND l.trip_id = t AND l.sequence IS DISTINCT FROM o.n;
END $$;
"""

REVERSE = r"""
DROP FUNCTION app.reorder_legs(bigint, bigint[]);
DROP TRIGGER media_refs_guard ON media_media;
DROP FUNCTION app.guard_media_refs();
DROP TRIGGER stop_refs_guard ON trips_stop;
DROP FUNCTION app.guard_stop_refs();
DROP TRIGGER stop_place_guard ON trips_stop;
DROP FUNCTION app.guard_stop_place();
DROP FUNCTION app.can_use_place(bigint, bigint);

ALTER POLICY media_delete ON media_media
  USING (author_id = app.user_id() AND app.is_family());
ALTER POLICY media_update ON media_media
  USING (author_id = app.user_id() AND app.media_visible(trip_id, vehicle_id, author_id))
  WITH CHECK (author_id = app.user_id());
ALTER POLICY triptag_delete ON trips_triptag
  USING (author_id = app.user_id() AND app.is_family());
ALTER POLICY track_delete ON trips_trackcontribution
  USING (author_id = app.user_id() AND app.is_family());
ALTER POLICY track_update ON trips_trackcontribution
  USING (author_id = app.user_id() AND app.can_view_trip(trip_id))
  WITH CHECK (author_id = app.user_id() AND app.can_view_trip(trip_id));
ALTER POLICY note_delete ON trips_tripnote
  USING (author_id = app.user_id() AND app.is_family());
ALTER POLICY note_update ON trips_tripnote
  USING (author_id = app.user_id() AND app.can_view_trip(trip_id))
  WITH CHECK (author_id = app.user_id() AND app.can_view_trip(trip_id));
ALTER POLICY leg_delete ON trips_leg
  USING ((NOT is_contribution AND app.can_edit_trip_core(trip_id))
         OR (is_contribution AND author_id = app.user_id() AND app.can_contribute(trip_id)));

DROP FUNCTION app.can_delete_left_contribution(bigint, bigint);
DROP FUNCTION app.is_person_on_trip(bigint, bigint);
DROP FUNCTION app.user_person(bigint);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("trips", "0003_trip_api_guards"),
        ("media", "0003_photo_limit"),
    ]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
