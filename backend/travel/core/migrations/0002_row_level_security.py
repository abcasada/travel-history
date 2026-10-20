"""Row-level security v1 (PLAN.md §6). Policies apply to the runtime role `travel_app`; the
owner role (migrations, dataset loads, backups) bypasses them because tables are not FORCEd
(PLAN.md D-23). `travel_public` has no policies and no grants on these tables.

Request context (set transaction-locally by travel.core.rls):
  app.user_id  the authenticated user, or empty
  app.ctx      a narrow system context for pre-authentication steps:
               'auth'   OIDC login: look up / create / update the user row
               'ingest' tracker ingestion: look up a device token by hash
               'public_form' request-access form: create a request, read allowlist/invites
               'transfer' accepting a transfer offer (owner change)

Helper functions are STABLE SECURITY DEFINER (owned by travel_owner, so they see all rows) with a
pinned search_path; that also prevents policy recursion between trips and participants.
Column-level rules that RLS cannot express are guard triggers at the end of this file.
"""

from django.db import migrations

HELPERS = r"""
CREATE SCHEMA IF NOT EXISTS app;

CREATE FUNCTION app.user_id() RETURNS bigint LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('app.user_id', true), '')::bigint
$$;

CREATE FUNCTION app.ctx() RETURNS text LANGUAGE sql STABLE AS $$
  SELECT coalesce(current_setting('app.ctx', true), '')
$$;

CREATE FUNCTION app.user_role() RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT role FROM accounts_user WHERE id = app.user_id() AND is_active
$$;

CREATE FUNCTION app.is_family() RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT app.user_role() IS NOT NULL
$$;

CREATE FUNCTION app.is_admin() RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT coalesce(app.user_role() = 'admin', false)
$$;

CREATE FUNCTION app.can_create() RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT coalesce(app.user_role() IN ('admin', 'member'), false)
$$;

CREATE FUNCTION app.person_id() RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT person_id FROM accounts_user WHERE id = app.user_id() AND is_active
$$;

-- My person is an effective participant of the trip: trip-level, or added to any leg.
CREATE FUNCTION app.is_trip_participant(t bigint) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT app.person_id() IS NOT NULL AND (
    EXISTS (SELECT 1 FROM trips_tripparticipant
             WHERE trip_id = t AND person_id = app.person_id())
    OR EXISTS (SELECT 1 FROM trips_legparticipantoverride o
                 JOIN trips_leg l ON l.id = o.leg_id
                WHERE l.trip_id = t AND o.person_id = app.person_id() AND o.include))
$$;

CREATE FUNCTION app.trip_visible(owner bigint, visibility text, t bigint) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT app.is_family() AND (
    owner = app.user_id()
    OR visibility IN ('family', 'public')
    OR (visibility = 'participants' AND app.is_trip_participant(t)))
$$;

CREATE FUNCTION app.can_view_trip(t bigint) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT EXISTS (SELECT 1 FROM trips_trip tr
                  WHERE tr.id = t AND app.trip_visible(tr.owner_id, tr.visibility, tr.id))
$$;

CREATE FUNCTION app.trip_owner(t bigint) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT owner_id FROM trips_trip WHERE id = t
$$;

-- Owner, or the Admin on any trip the Admin can see.
CREATE FUNCTION app.can_edit_trip_core(t bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT app.is_family() AND (
    app.trip_owner(t) = app.user_id() OR (app.is_admin() AND app.can_view_trip(t)))
$$;

-- Members/Admin who are the owner or a participant may add contributions.
CREATE FUNCTION app.can_contribute(t bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT app.can_create() AND app.can_view_trip(t)
     AND (app.trip_owner(t) = app.user_id() OR app.is_trip_participant(t))
$$;

CREATE FUNCTION app.leg_trip(l bigint) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT trip_id FROM trips_leg WHERE id = l
$$;

CREATE FUNCTION app.can_edit_leg(l bigint) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT EXISTS (
    SELECT 1 FROM trips_leg lg WHERE lg.id = l AND (
      (NOT lg.is_contribution AND app.can_edit_trip_core(lg.trip_id))
      OR (lg.is_contribution AND lg.author_id = app.user_id() AND app.can_contribute(lg.trip_id))))
$$;

CREATE FUNCTION app.route_leg(r bigint) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT leg_id FROM trips_route WHERE id = r
$$;

-- The managing user of a person: its linked account, else whoever created it.
CREATE FUNCTION app.manages_person(p bigint) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT app.is_family() AND EXISTS (
    SELECT 1 FROM accounts_person pe
      LEFT JOIN accounts_user u ON u.person_id = pe.id
     WHERE pe.id = p
       AND (u.id = app.user_id() OR (u.id IS NULL AND pe.created_by_id = app.user_id())))
$$;

-- Current owner's account if the owner person has one, else the creator of the record.
CREATE FUNCTION app.vehicle_manager(v bigint) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT coalesce(
    (SELECT u.id FROM vehicles_vehicleownership vo
       JOIN accounts_user u ON u.person_id = vo.owner_person_id AND u.is_active
      WHERE vo.vehicle_id = v
        AND (vo.valid_from IS NULL OR vo.valid_from <= current_date)
        AND (vo.valid_to IS NULL OR vo.valid_to > current_date)
      LIMIT 1),
    (SELECT created_by_id FROM vehicles_vehicle WHERE id = v))
$$;

CREATE FUNCTION app.can_view_vehicle(v bigint) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT app.is_family() AND EXISTS (
    SELECT 1 FROM vehicles_vehicle ve
     WHERE ve.id = v
       AND (NOT ve.hidden OR ve.created_by_id = app.user_id()
            OR app.vehicle_manager(v) = app.user_id()))
$$;

CREATE FUNCTION app.can_manage_vehicle(v bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT app.is_family() AND (
    app.vehicle_manager(v) = app.user_id() OR (app.is_admin() AND app.can_view_vehicle(v)))
$$;

CREATE FUNCTION app.can_view_person(p bigint) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT app.is_family() AND EXISTS (
    SELECT 1 FROM accounts_person pe
     WHERE pe.id = p AND (
       pe.visibility = 'family'
       OR pe.created_by_id = app.user_id()
       OR pe.id = app.person_id()
       OR EXISTS (SELECT 1 FROM trips_tripparticipant tp
                   WHERE tp.person_id = pe.id AND app.can_view_trip(tp.trip_id))
       OR EXISTS (SELECT 1 FROM trips_legparticipantoverride o
                    JOIN trips_leg l ON l.id = o.leg_id
                   WHERE o.person_id = pe.id AND app.can_view_trip(l.trip_id))
       OR EXISTS (SELECT 1 FROM vehicles_vehicleownership vo
                   WHERE vo.owner_person_id = pe.id AND app.can_view_vehicle(vo.vehicle_id))))
$$;

CREATE FUNCTION app.can_view_place(pl bigint) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT app.is_family() AND EXISTS (
    SELECT 1 FROM trips_place p WHERE p.id = pl AND (
      p.owner_id = app.user_id()
      OR EXISTS (SELECT 1 FROM trips_stop s
                  WHERE s.place_id = p.id AND app.can_view_trip(s.trip_id))))
$$;

CREATE FUNCTION app.can_view_tag(tg bigint) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT app.is_family() AND EXISTS (
    SELECT 1 FROM trips_tag t WHERE t.id = tg AND (
      t.owner_id = app.user_id()
      OR EXISTS (SELECT 1 FROM trips_triptag tt
                  WHERE tt.tag_id = t.id AND app.can_view_trip(tt.trip_id))))
$$;

CREATE FUNCTION app.can_view_purpose(pu bigint) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT app.is_family() AND EXISTS (
    SELECT 1 FROM trips_purpose p WHERE p.id = pu AND (
      p.owner_id = app.user_id()
      OR EXISTS (SELECT 1 FROM trips_trip tr
                  WHERE tr.purpose_id = p.id
                    AND app.trip_visible(tr.owner_id, tr.visibility, tr.id))))
$$;

-- Media visibility: trip media follow the trip; vehicle photos follow the vehicle; anything
-- else (avatars) only its author.
CREATE FUNCTION app.media_visible(trip bigint, vehicle bigint, author bigint) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT app.is_family() AND CASE
    WHEN trip IS NOT NULL THEN app.can_view_trip(trip)
    WHEN vehicle IS NOT NULL THEN app.can_view_vehicle(vehicle)
    ELSE author = app.user_id()
  END
$$;
"""

POLICIES = r"""
-- ===== accounts ==========================================================================
ALTER TABLE accounts_user ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_select ON accounts_user FOR SELECT TO travel_app
  USING (id = app.user_id() OR app.is_family() OR app.ctx() = 'auth');
CREATE POLICY user_insert ON accounts_user FOR INSERT TO travel_app
  WITH CHECK (app.ctx() = 'auth' OR app.is_admin());
CREATE POLICY user_update ON accounts_user FOR UPDATE TO travel_app
  USING (id = app.user_id() OR app.is_admin() OR app.ctx() = 'auth')
  WITH CHECK (id = app.user_id() OR app.is_admin() OR app.ctx() = 'auth');
-- No DELETE policy: accounts are deactivated, never deleted by the app.

ALTER TABLE accounts_person ENABLE ROW LEVEL SECURITY;
-- SELECT policies check the row's own columns first: a by-id lookup cannot see a row inserted
-- by the same statement, which INSERT ... RETURNING needs.
CREATE POLICY person_select ON accounts_person FOR SELECT TO travel_app
  USING ((app.is_family() AND (visibility = 'family' OR created_by_id = app.user_id()))
         OR app.can_view_person(id));
CREATE POLICY person_insert ON accounts_person FOR INSERT TO travel_app
  WITH CHECK (app.can_create() AND created_by_id = app.user_id());
CREATE POLICY person_update ON accounts_person FOR UPDATE TO travel_app
  USING (app.manages_person(id) OR app.is_admin())
  WITH CHECK (app.manages_person(id) OR app.is_admin());
CREATE POLICY person_delete ON accounts_person FOR DELETE TO travel_app
  USING (app.manages_person(id));

ALTER TABLE accounts_userpreference ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_all ON accounts_userpreference FOR ALL TO travel_app
  USING (user_id = app.user_id() AND app.is_family())
  WITH CHECK (user_id = app.user_id() AND app.is_family());

ALTER TABLE accounts_pushsubscription ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_all ON accounts_pushsubscription FOR ALL TO travel_app
  USING (user_id = app.user_id() AND app.is_family())
  WITH CHECK (user_id = app.user_id() AND app.is_family());

ALTER TABLE accounts_integrationsetting ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_all ON accounts_integrationsetting FOR ALL TO travel_app
  USING (user_id = app.user_id() AND app.is_family())
  WITH CHECK (user_id = app.user_id() AND app.is_family());

ALTER TABLE accounts_publicprofile ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_all ON accounts_publicprofile FOR ALL TO travel_app
  USING (user_id = app.user_id() AND app.is_family())
  WITH CHECK (user_id = app.user_id() AND app.is_family());

ALTER TABLE accounts_devicetoken ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_all ON accounts_devicetoken FOR ALL TO travel_app
  USING (user_id = app.user_id() AND app.is_family())
  WITH CHECK (user_id = app.user_id() AND app.is_family() AND app.can_create());
-- Ingestion looks a token up by its hash before the owner is known.
CREATE POLICY ingest_lookup ON accounts_devicetoken FOR SELECT TO travel_app
  USING (app.ctx() = 'ingest');

ALTER TABLE accounts_accessrequest ENABLE ROW LEVEL SECURITY;
CREATE POLICY admin_all ON accounts_accessrequest FOR ALL TO travel_app
  USING (app.is_admin()) WITH CHECK (app.is_admin());
CREATE POLICY form_insert ON accounts_accessrequest FOR INSERT TO travel_app
  WITH CHECK (app.ctx() = 'public_form' AND status = 'pending' AND decided_by_id IS NULL);
-- INSERT ... RETURNING also needs SELECT: allow reading back only rows this transaction created.
CREATE POLICY form_returning ON accounts_accessrequest FOR SELECT TO travel_app
  USING (app.ctx() = 'public_form' AND xmin = pg_current_xact_id()::xid);

ALTER TABLE accounts_allowlistentry ENABLE ROW LEVEL SECURITY;
CREATE POLICY admin_all ON accounts_allowlistentry FOR ALL TO travel_app
  USING (app.is_admin()) WITH CHECK (app.is_admin());
CREATE POLICY form_lookup ON accounts_allowlistentry FOR SELECT TO travel_app
  USING (app.ctx() = 'public_form');

ALTER TABLE accounts_invite ENABLE ROW LEVEL SECURITY;
CREATE POLICY admin_all ON accounts_invite FOR ALL TO travel_app
  USING (app.is_admin()) WITH CHECK (app.is_admin());
CREATE POLICY form_lookup ON accounts_invite FOR SELECT TO travel_app
  USING (app.ctx() = 'public_form');
CREATE POLICY form_mark_used ON accounts_invite FOR UPDATE TO travel_app
  USING (app.ctx() = 'public_form' AND used_at IS NULL)
  WITH CHECK (app.ctx() = 'public_form');

ALTER TABLE accounts_auditlog ENABLE ROW LEVEL SECURITY;
CREATE POLICY audit_select ON accounts_auditlog FOR SELECT TO travel_app
  USING (app.is_admin());
CREATE POLICY audit_insert ON accounts_auditlog FOR INSERT TO travel_app
  WITH CHECK (actor_id IS NOT DISTINCT FROM app.user_id());
CREATE POLICY audit_returning ON accounts_auditlog FOR SELECT TO travel_app
  USING (xmin = pg_current_xact_id()::xid);
-- No UPDATE/DELETE policies: the audit log is append-only for the app.

-- ===== trips =============================================================================
ALTER TABLE trips_purpose ENABLE ROW LEVEL SECURITY;
CREATE POLICY purpose_select ON trips_purpose FOR SELECT TO travel_app
  USING ((owner_id = app.user_id() AND app.is_family()) OR app.can_view_purpose(id));
CREATE POLICY purpose_write ON trips_purpose FOR INSERT TO travel_app
  WITH CHECK (owner_id = app.user_id() AND app.can_create());
CREATE POLICY purpose_update ON trips_purpose FOR UPDATE TO travel_app
  USING (owner_id = app.user_id() AND app.is_family())
  WITH CHECK (owner_id = app.user_id() AND app.is_family());
CREATE POLICY purpose_delete ON trips_purpose FOR DELETE TO travel_app
  USING (owner_id = app.user_id() AND app.is_family());

ALTER TABLE trips_trip ENABLE ROW LEVEL SECURITY;
CREATE POLICY trip_select ON trips_trip FOR SELECT TO travel_app
  USING (app.trip_visible(owner_id, visibility, id));
CREATE POLICY trip_insert ON trips_trip FOR INSERT TO travel_app
  WITH CHECK (owner_id = app.user_id() AND app.can_create());
CREATE POLICY trip_update ON trips_trip FOR UPDATE TO travel_app
  USING (app.is_family() AND (owner_id = app.user_id()
         OR (app.is_admin() AND app.trip_visible(owner_id, visibility, id))))
  WITH CHECK (app.is_family() AND (owner_id = app.user_id() OR app.is_admin()));
CREATE POLICY trip_delete ON trips_trip FOR DELETE TO travel_app
  USING (owner_id = app.user_id() AND app.is_family());

ALTER TABLE trips_leg ENABLE ROW LEVEL SECURITY;
CREATE POLICY leg_select ON trips_leg FOR SELECT TO travel_app
  USING (app.can_view_trip(trip_id));
CREATE POLICY leg_insert ON trips_leg FOR INSERT TO travel_app
  WITH CHECK (author_id = app.user_id() AND (
    (NOT is_contribution AND app.can_edit_trip_core(trip_id))
    OR (is_contribution AND app.can_contribute(trip_id))));
CREATE POLICY leg_update ON trips_leg FOR UPDATE TO travel_app
  USING ((NOT is_contribution AND app.can_edit_trip_core(trip_id))
         OR (is_contribution AND author_id = app.user_id() AND app.can_contribute(trip_id)))
  WITH CHECK ((NOT is_contribution AND app.can_edit_trip_core(trip_id))
              OR (is_contribution AND author_id = app.user_id()
                  AND app.can_contribute(trip_id)));
CREATE POLICY leg_delete ON trips_leg FOR DELETE TO travel_app
  USING ((NOT is_contribution AND app.can_edit_trip_core(trip_id))
         OR (is_contribution AND author_id = app.user_id()));

ALTER TABLE trips_route ENABLE ROW LEVEL SECURITY;
CREATE POLICY route_select ON trips_route FOR SELECT TO travel_app
  USING (app.can_view_trip(app.leg_trip(leg_id)));
CREATE POLICY route_insert ON trips_route FOR INSERT TO travel_app
  WITH CHECK (created_by_id = app.user_id() AND app.can_edit_leg(leg_id));
CREATE POLICY route_delete ON trips_route FOR DELETE TO travel_app
  USING (app.can_edit_leg(leg_id));
-- No UPDATE policy: saved routes are frozen (and a trigger rejects updates).

ALTER TABLE trips_routesimplified ENABLE ROW LEVEL SECURITY;
CREATE POLICY routesimp_select ON trips_routesimplified FOR SELECT TO travel_app
  USING (app.can_view_trip(app.leg_trip(app.route_leg(route_id))));
CREATE POLICY routesimp_insert ON trips_routesimplified FOR INSERT TO travel_app
  WITH CHECK (app.can_edit_leg(app.route_leg(route_id)));
CREATE POLICY routesimp_delete ON trips_routesimplified FOR DELETE TO travel_app
  USING (app.can_edit_leg(app.route_leg(route_id)));

ALTER TABLE trips_tripparticipant ENABLE ROW LEVEL SECURITY;
CREATE POLICY participant_select ON trips_tripparticipant FOR SELECT TO travel_app
  USING (app.can_view_trip(trip_id));
CREATE POLICY participant_insert ON trips_tripparticipant FOR INSERT TO travel_app
  WITH CHECK (app.can_edit_trip_core(trip_id) AND added_by_id = app.user_id());
-- Core editors manage the list; a participant (or their managing user) may update their own
-- row, and the guard trigger limits that to public_consent.
CREATE POLICY participant_update ON trips_tripparticipant FOR UPDATE TO travel_app
  USING (app.can_edit_trip_core(trip_id)
         OR (app.manages_person(person_id) AND app.can_view_trip(trip_id)))
  WITH CHECK (app.can_edit_trip_core(trip_id)
              OR (app.manages_person(person_id) AND app.can_view_trip(trip_id)));
CREATE POLICY participant_delete ON trips_tripparticipant FOR DELETE TO travel_app
  USING (app.can_edit_trip_core(trip_id));

ALTER TABLE trips_legparticipantoverride ENABLE ROW LEVEL SECURITY;
CREATE POLICY legoverride_select ON trips_legparticipantoverride FOR SELECT TO travel_app
  USING (app.can_view_trip(app.leg_trip(leg_id)));
CREATE POLICY legoverride_write ON trips_legparticipantoverride FOR ALL TO travel_app
  USING (app.can_edit_trip_core(app.leg_trip(leg_id))
         OR (app.manages_person(person_id) AND app.can_contribute(app.leg_trip(leg_id))))
  WITH CHECK (set_by_id = app.user_id() AND (
    app.can_edit_trip_core(app.leg_trip(leg_id))
    OR (app.manages_person(person_id) AND app.can_contribute(app.leg_trip(leg_id)))));

ALTER TABLE trips_place ENABLE ROW LEVEL SECURITY;
CREATE POLICY place_select ON trips_place FOR SELECT TO travel_app
  USING ((owner_id = app.user_id() AND app.is_family()) OR app.can_view_place(id));
CREATE POLICY place_write ON trips_place FOR INSERT TO travel_app
  WITH CHECK (owner_id = app.user_id() AND app.can_create());
CREATE POLICY place_update ON trips_place FOR UPDATE TO travel_app
  USING (owner_id = app.user_id() AND app.is_family())
  WITH CHECK (owner_id = app.user_id() AND app.is_family());
CREATE POLICY place_delete ON trips_place FOR DELETE TO travel_app
  USING (owner_id = app.user_id() AND app.is_family());

-- Stops (lodging, destinations) are part of the trip's core itinerary.
ALTER TABLE trips_stop ENABLE ROW LEVEL SECURITY;
CREATE POLICY stop_select ON trips_stop FOR SELECT TO travel_app
  USING (app.can_view_trip(trip_id));
CREATE POLICY stop_write ON trips_stop FOR ALL TO travel_app
  USING (app.can_edit_trip_core(trip_id))
  WITH CHECK (app.can_edit_trip_core(trip_id));

ALTER TABLE trips_tag ENABLE ROW LEVEL SECURITY;
CREATE POLICY tag_select ON trips_tag FOR SELECT TO travel_app
  USING ((owner_id = app.user_id() AND app.is_family()) OR app.can_view_tag(id));
CREATE POLICY tag_insert ON trips_tag FOR INSERT TO travel_app
  WITH CHECK (owner_id = app.user_id() AND app.can_create());
CREATE POLICY tag_update ON trips_tag FOR UPDATE TO travel_app
  USING (owner_id = app.user_id() AND app.is_family())
  WITH CHECK (owner_id = app.user_id() AND app.is_family());
CREATE POLICY tag_delete ON trips_tag FOR DELETE TO travel_app
  USING (owner_id = app.user_id() AND app.is_family());

ALTER TABLE trips_triptag ENABLE ROW LEVEL SECURITY;
CREATE POLICY triptag_select ON trips_triptag FOR SELECT TO travel_app
  USING (app.can_view_trip(trip_id));
CREATE POLICY triptag_insert ON trips_triptag FOR INSERT TO travel_app
  WITH CHECK (author_id = app.user_id() AND app.can_contribute(trip_id)
              AND EXISTS (SELECT 1 FROM trips_tag t WHERE t.id = tag_id
                           AND t.owner_id = app.user_id()));
CREATE POLICY triptag_delete ON trips_triptag FOR DELETE TO travel_app
  USING (author_id = app.user_id() AND app.is_family());

ALTER TABLE trips_tripnote ENABLE ROW LEVEL SECURITY;
CREATE POLICY note_select ON trips_tripnote FOR SELECT TO travel_app
  USING (app.can_view_trip(trip_id));
CREATE POLICY note_insert ON trips_tripnote FOR INSERT TO travel_app
  WITH CHECK (author_id = app.user_id() AND app.can_contribute(trip_id));
CREATE POLICY note_update ON trips_tripnote FOR UPDATE TO travel_app
  USING (author_id = app.user_id() AND app.can_view_trip(trip_id))
  WITH CHECK (author_id = app.user_id() AND app.can_view_trip(trip_id));
CREATE POLICY note_delete ON trips_tripnote FOR DELETE TO travel_app
  USING (author_id = app.user_id() AND app.is_family());

ALTER TABLE trips_trackcontribution ENABLE ROW LEVEL SECURITY;
CREATE POLICY track_select ON trips_trackcontribution FOR SELECT TO travel_app
  USING (app.can_view_trip(trip_id));
CREATE POLICY track_insert ON trips_trackcontribution FOR INSERT TO travel_app
  WITH CHECK (author_id = app.user_id() AND app.can_contribute(trip_id));
CREATE POLICY track_update ON trips_trackcontribution FOR UPDATE TO travel_app
  USING (author_id = app.user_id() AND app.can_view_trip(trip_id))
  WITH CHECK (author_id = app.user_id() AND app.can_view_trip(trip_id));
CREATE POLICY track_delete ON trips_trackcontribution FOR DELETE TO travel_app
  USING (author_id = app.user_id() AND app.is_family());

ALTER TABLE trips_reviewflag ENABLE ROW LEVEL SECURITY;
CREATE POLICY flag_all ON trips_reviewflag FOR ALL TO travel_app
  USING (app.can_edit_trip_core(trip_id))
  WITH CHECK (app.can_edit_trip_core(trip_id));

ALTER TABLE trips_rejectedcandidate ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_all ON trips_rejectedcandidate FOR ALL TO travel_app
  USING (owner_id = app.user_id() AND app.is_family())
  WITH CHECK (owner_id = app.user_id() AND app.is_family());

ALTER TABLE trips_transferoffer ENABLE ROW LEVEL SECURITY;
CREATE POLICY transfer_select ON trips_transferoffer FOR SELECT TO travel_app
  USING (app.is_family() AND (from_user_id = app.user_id() OR to_user_id = app.user_id()
                              OR app.is_admin()));
CREATE POLICY transfer_insert ON trips_transferoffer FOR INSERT TO travel_app
  WITH CHECK (app.is_family() AND (from_user_id = app.user_id() OR app.is_admin()));
CREATE POLICY transfer_update ON trips_transferoffer FOR UPDATE TO travel_app
  USING (app.is_family() AND (from_user_id = app.user_id() OR to_user_id = app.user_id()))
  WITH CHECK (app.is_family() AND (from_user_id = app.user_id() OR to_user_id = app.user_id()));
CREATE POLICY transfer_delete ON trips_transferoffer FOR DELETE TO travel_app
  USING (app.is_family() AND (from_user_id = app.user_id() OR app.is_admin()));

-- ===== vehicles ==========================================================================
ALTER TABLE vehicles_vehicle ENABLE ROW LEVEL SECURITY;
CREATE POLICY vehicle_select ON vehicles_vehicle FOR SELECT TO travel_app
  USING (app.is_family() AND (NOT hidden OR created_by_id = app.user_id()
                              OR app.vehicle_manager(id) = app.user_id()));
CREATE POLICY vehicle_insert ON vehicles_vehicle FOR INSERT TO travel_app
  WITH CHECK (created_by_id = app.user_id() AND app.can_create());
CREATE POLICY vehicle_update ON vehicles_vehicle FOR UPDATE TO travel_app
  USING (app.can_manage_vehicle(id)) WITH CHECK (app.can_manage_vehicle(id));
CREATE POLICY vehicle_delete ON vehicles_vehicle FOR DELETE TO travel_app
  USING (app.is_family() AND app.vehicle_manager(id) = app.user_id());

ALTER TABLE vehicles_vehicleprivate ENABLE ROW LEVEL SECURITY;
CREATE POLICY private_all ON vehicles_vehicleprivate FOR ALL TO travel_app
  USING (app.is_family() AND app.vehicle_manager(vehicle_id) = app.user_id())
  WITH CHECK (app.is_family() AND app.vehicle_manager(vehicle_id) = app.user_id());

ALTER TABLE vehicles_vehicleownership ENABLE ROW LEVEL SECURITY;
CREATE POLICY ownership_select ON vehicles_vehicleownership FOR SELECT TO travel_app
  USING (app.can_view_vehicle(vehicle_id));
CREATE POLICY ownership_write ON vehicles_vehicleownership FOR ALL TO travel_app
  USING (app.can_manage_vehicle(vehicle_id))
  WITH CHECK (app.can_manage_vehicle(vehicle_id));

-- ===== history (raw data: owner only, never the Admin) =====================================
ALTER TABLE history_rawfile ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_select ON history_rawfile FOR SELECT TO travel_app
  USING (owner_id = app.user_id() AND app.is_family());
CREATE POLICY own_insert ON history_rawfile FOR INSERT TO travel_app
  WITH CHECK (owner_id = app.user_id() AND app.can_create());
CREATE POLICY own_delete ON history_rawfile FOR DELETE TO travel_app
  USING (owner_id = app.user_id() AND app.is_family());

ALTER TABLE history_locationpoint ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_select ON history_locationpoint FOR SELECT TO travel_app
  USING (owner_id = app.user_id() AND app.is_family());
CREATE POLICY own_insert ON history_locationpoint FOR INSERT TO travel_app
  WITH CHECK (owner_id = app.user_id() AND app.is_family());
CREATE POLICY own_delete ON history_locationpoint FOR DELETE TO travel_app
  USING (owner_id = app.user_id() AND app.is_family());

ALTER TABLE history_importbatch ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_all ON history_importbatch FOR ALL TO travel_app
  USING (owner_id = app.user_id() AND app.is_family())
  WITH CHECK (owner_id = app.user_id() AND app.can_create());

ALTER TABLE history_timelinesegment ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_all ON history_timelinesegment FOR ALL TO travel_app
  USING (owner_id = app.user_id() AND app.is_family())
  WITH CHECK (owner_id = app.user_id() AND app.is_family());

ALTER TABLE history_coveragereport ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_all ON history_coveragereport FOR ALL TO travel_app
  USING (owner_id = app.user_id() AND app.is_family())
  WITH CHECK (owner_id = app.user_id() AND app.is_family());

ALTER TABLE history_detectionrun ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_all ON history_detectionrun FOR ALL TO travel_app
  USING (owner_id = app.user_id() AND app.is_family())
  WITH CHECK (owner_id = app.user_id() AND app.is_family());

ALTER TABLE history_homeperiod ENABLE ROW LEVEL SECURITY;
CREATE POLICY home_select ON history_homeperiod FOR SELECT TO travel_app
  USING (app.is_family() AND (managed_by_id = app.user_id() OR shared_with_family));
CREATE POLICY home_write ON history_homeperiod FOR ALL TO travel_app
  USING (managed_by_id = app.user_id() AND app.is_family())
  WITH CHECK (managed_by_id = app.user_id() AND app.is_family()
              AND app.manages_person(person_id));

-- ===== media =============================================================================
ALTER TABLE media_media ENABLE ROW LEVEL SECURITY;
CREATE POLICY media_select ON media_media FOR SELECT TO travel_app
  USING (app.media_visible(trip_id, vehicle_id, author_id));
CREATE POLICY media_insert ON media_media FOR INSERT TO travel_app
  WITH CHECK (author_id = app.user_id() AND app.can_create() AND CASE
    WHEN trip_id IS NOT NULL THEN app.can_contribute(trip_id)
    WHEN vehicle_id IS NOT NULL THEN app.can_manage_vehicle(vehicle_id)
    ELSE true END);
CREATE POLICY media_update ON media_media FOR UPDATE TO travel_app
  USING (author_id = app.user_id() AND app.media_visible(trip_id, vehicle_id, author_id))
  WITH CHECK (author_id = app.user_id());
CREATE POLICY media_delete ON media_media FOR DELETE TO travel_app
  USING (author_id = app.user_id() AND app.is_family());
"""

GUARDS = r"""
-- Guards run with the invoker's rights (not SECURITY DEFINER) so that current_user is the
-- calling role: the owner role (migrations, management commands) is exempt, travel_app is not.
-- accounts_user: users cannot change their own role or identity; linking to a person needs
-- the Admin, or a person the user manages. The owner role (management commands) is exempt.
CREATE FUNCTION app.guard_user_update() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
  IF current_user = 'travel_owner' THEN
    RETURN NEW;
  END IF;
  IF NEW.role IS DISTINCT FROM OLD.role AND NOT app.is_admin() THEN
    RAISE EXCEPTION 'only the Admin can change roles' USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF (NEW.oidc_issuer, NEW.oidc_sub, NEW.email) IS DISTINCT FROM
     (OLD.oidc_issuer, OLD.oidc_sub, OLD.email) AND app.ctx() <> 'auth' THEN
    RAISE EXCEPTION 'identity fields change only at login' USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF NEW.is_active IS DISTINCT FROM OLD.is_active AND NOT app.is_admin() THEN
    RAISE EXCEPTION 'only the Admin can (de)activate accounts' USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF NEW.person_id IS DISTINCT FROM OLD.person_id AND NOT (
       app.is_admin()
       OR (NEW.id = app.user_id() AND (NEW.person_id IS NULL OR app.manages_person(NEW.person_id)))) THEN
    RAISE EXCEPTION 'cannot link this account to that person' USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER user_guard BEFORE UPDATE ON accounts_user
FOR EACH ROW EXECUTE FUNCTION app.guard_user_update();

-- New users created at login are always Members (the Admin promotes; bootstrap uses the owner).
CREATE FUNCTION app.guard_user_insert() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
  IF current_user <> 'travel_owner' AND NEW.role = 'admin' AND NOT app.is_admin() THEN
    RAISE EXCEPTION 'new accounts cannot start as Admin' USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER user_insert_guard BEFORE INSERT ON accounts_user
FOR EACH ROW EXECUTE FUNCTION app.guard_user_insert();

-- trips_trip: the owner changes only through a transfer (or the owner role).
CREATE FUNCTION app.guard_trip_update() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
  IF NEW.owner_id IS DISTINCT FROM OLD.owner_id
     AND app.ctx() <> 'transfer' AND current_user <> 'travel_owner' THEN
    RAISE EXCEPTION 'trip ownership changes only through a transfer'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trip_guard BEFORE UPDATE ON trips_trip
FOR EACH ROW EXECUTE FUNCTION app.guard_trip_update();

-- trips_leg: author and contribution status are fixed at creation.
CREATE FUNCTION app.guard_leg_update() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
  IF current_user <> 'travel_owner' AND app.ctx() <> 'transfer' AND
     (NEW.author_id, NEW.is_contribution, NEW.trip_id)
       IS DISTINCT FROM (OLD.author_id, OLD.is_contribution, OLD.trip_id) THEN
    RAISE EXCEPTION 'leg author, trip and contribution status cannot change'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER leg_guard BEFORE UPDATE ON trips_leg
FOR EACH ROW EXECUTE FUNCTION app.guard_leg_update();

-- trips_tripparticipant: only the participant (or their managing user) sets public_consent;
-- someone who is not a core editor may change nothing else.
CREATE FUNCTION app.guard_participant_update() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
  IF current_user = 'travel_owner' THEN
    RETURN NEW;
  END IF;
  IF NEW.public_consent IS DISTINCT FROM OLD.public_consent
     AND NOT app.manages_person(OLD.person_id) THEN
    RAISE EXCEPTION 'only the participant decides their public consent'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF (NEW.trip_id, NEW.person_id, NEW.added_by_id) IS DISTINCT FROM
     (OLD.trip_id, OLD.person_id, OLD.added_by_id) AND NOT app.can_edit_trip_core(OLD.trip_id) THEN
    RAISE EXCEPTION 'participants may only change their consent'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER participant_guard BEFORE UPDATE ON trips_tripparticipant
FOR EACH ROW EXECUTE FUNCTION app.guard_participant_update();

-- Contributions keep their author.
CREATE FUNCTION app.guard_author_fixed() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.author_id IS DISTINCT FROM OLD.author_id AND current_user <> 'travel_owner'
     AND app.ctx() <> 'transfer' THEN
    RAISE EXCEPTION 'the author of a contribution cannot change'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER note_author_fixed BEFORE UPDATE ON trips_tripnote
FOR EACH ROW EXECUTE FUNCTION app.guard_author_fixed();
CREATE TRIGGER media_author_fixed BEFORE UPDATE ON media_media
FOR EACH ROW EXECUTE FUNCTION app.guard_author_fixed();
CREATE TRIGGER track_author_fixed BEFORE UPDATE ON trips_trackcontribution
FOR EACH ROW EXECUTE FUNCTION app.guard_author_fixed();
"""

REVERSE = "DROP SCHEMA app CASCADE;"


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
        ("accounts", "0002_initial"),
        ("trips", "0002_route_immutable"),
        ("vehicles", "0002_ownership_continuity"),
        ("history", "0002_append_only"),
        ("media", "0003_photo_limit"),
        ("public", "0001_initial"),
        ("geo", "0001_initial"),
    ]
    operations = [migrations.RunSQL(HELPERS + POLICIES + GUARDS, REVERSE)]
