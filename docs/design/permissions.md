# Permissions and visibility

Moved from PLAN.md §6 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 6. Permissions and visibility

### 6.1 Principles

- Enforced twice: in the app (`travel.core.policy`, consulted by every endpoint) **and** in PostgreSQL
  with row-level security. Either layer alone must be enough to stop a leak; tests exercise both.
- Fail closed. Every request runs inside a transaction that sets
  `set_config('app.user_id', <id>, true)` (transaction-local). If it is unset, every policy
  evaluates to false.
- The runtime role `travel_app` does not own any table and has `NOBYPASSRLS`. Policy helper
  functions live in schema `app`, are `STABLE SECURITY DEFINER` (owned by `travel_owner`) with a
  pinned `search_path`; this also avoids policy recursion between `trip` and `trip_participant`.
- The Admin is an app role, not a database superuser. The Admin cannot see other users' private
  trips or anyone's raw history; RLS enforces this too.
- "Family" means every active account (Admin, Member, Viewer). The app is single-family by design.

### 6.2 Trip visibility

| Visibility | Who can read the trip and its legs, routes, notes, photos, tags |
|---|---|
| private | the owner only |
| participants | the owner + users whose person is an effective participant (trip-level or any leg) |
| family | every active account |
| public | every active account + anonymous visitors, but anonymous visitors only through the public renderer and only allowlisted fields (§6.5) |

Default visibility comes from the purpose (Work → private, everything else → participants) and
is configurable per user. Contributions always follow the trip's visibility.

### 6.3 Permission matrix (role × action × object)

Legend: ✅ allowed · ❌ denied · "own" = only rows they authored · "vis" = only if they can see the
object under §6.2. "Participant" means a Member whose person participates in the trip.

| Object / action | Admin | Member — owner | Member — participant | Member — other | Viewer | Anonymous |
|---|---|---|---|---|---|---|
| Trip: read | vis | ✅ | vis | vis | vis | public renderer only |
| Trip: create | ✅ | ✅ | — | ✅ | ❌ | ❌ |
| Trip core: edit title, dates, purpose, cover, visibility, participants, core legs, routes | vis | ✅ | ❌ | ❌ | ❌ | ❌ |
| Trip: delete | ❌ (decision D-17) | ✅ | ❌ | ❌ | ❌ | ❌ |
| Trip visibility: change it so the editor no longer sees the trip | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Trip sharing settings (public mode, unlisted-link slug, privacy zone): read | vis | ✅ | ❌ | ❌ | ❌ | ❌ |
| Trip purpose: set (only the trip owner's own purposes) | vis | ✅ | ❌ | ❌ | ❌ | ❌ |
| Legs, participants (trip-level and per leg), participants' consent: read | vis | ✅ | vis | vis | vis | ❌ |
| Participants: add (only people the editor can see) / remove | vis | ✅ | ❌ | ❌ | ❌ | ❌ |
| Notes, photos, own legs, own tags, own GPS track: add | vis + participant | ✅ | ✅ | ❌ | ❌ | ❌ |
| Contributions: edit / delete | own | own | own | ❌ | ❌ | ❌ |
| Which legs *I* was on (own overrides) | own person | own person | own person | ❌ | ❌ | ❌ |
| Who was on a leg (anyone's overrides) | vis (people they can see) | ✅ (people they can see) | ❌ | ❌ | ❌ | ❌ |
| Public consent for my name/notes/photos/legs | own | own | own | ❌ | own | ❌ |
| Raw history (points, segments, imports, coverage; also the history map's tiles and coverage strip) | own only | own only | own only | own only | ❌ (no imports) | ❌ |
| Home periods | own; family-shared ones read-only | own; shared read-only | — | shared read-only | shared read-only | ❌ |
| Tags (definitions) | own | own | own | own | ❌ | ❌ |
| Person: create | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| Person: edit | ✅ | managing user | managing user | managing user | ❌ | ❌ |
| Vehicle: read | vis (not hidden, or managing) | managing or not hidden | same | same | not hidden | ❌ |
| Vehicle: use on own legs | any visible | any visible | any visible | any visible | ❌ | ❌ |
| A leg's vehicle: read (shown as none if the reader can't see the vehicle) | same as Vehicle: read | same | same | same | same | ❌ |
| Vehicle: edit / ownership history / merge | if visible | managing user | managing user | managing user | ❌ | ❌ |
| Vehicle plate / VIN: read | ❌ unless managing | managing user | managing user | managing user | ❌ | ❌ |
| Account: email, OIDC issuer/subject, role (the `user` row) | ✅ | own | own | own | own | ❌ |
| Account: display name, linked person, active flag (directory, D-76) | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Device tokens, push subscriptions, integrations, preferences | own | own | own | own | own (prefs, push) | ❌ |
| Tracker ingestion (write points) | — | — | — | — | — | device token only (write-only) |
| Access requests, allowlist, invites, roles | ✅ | ❌ | ❌ | ❌ | ❌ | submit request only |
| Transfer offers | create/confirm | accept/decline own | — | — | — | ❌ |
| Public profile | own | own | own | own | own | read if enabled |
| Merge duplicate trips | if can edit both | if owner of the surviving trip | ❌ | ❌ | ❌ | ❌ |

Notes:
- A *core* leg is one created by the owner or the Admin (`is_contribution = false`). A
  contributor's leg (`is_contribution = true`) is edited only by its author.
- Viewers are read-only. To contribute, a user must be a Member (Open question Q-6).
- History map (milestone 2.3): the point/segment tiles and coverage strip are reads of raw
  history, not a new action. RLS alone limits them to the caller's rows (the builders never
  filter by owner); `tests/permissions/test_history_tiles.py` checks every actor through the API
  and by calling the builders as `travel_app` under each RLS context, with another user's points
  in the same aggregated cell. A Viewer gets empty tiles (Viewers have no raw history).
- Accounts (D-72, D-76): a deactivated account reads nothing, not even its own row (D-53). Other
  users' accounts are read only through the `accounts_userdirectory` view, never the `user` table.
- Trips API (work-order item 6, D-81; endpoints in [api.md](api.md) §17):
  - Every endpoint asks `travel.core.policy` and runs under RLS. A trip the caller can't see
    answers **404** (its existence isn't revealed), a visible trip they may not change **403**,
    a signed-out or deactivated caller **401**. A hidden or missing reference (person, purpose,
    vehicle) gets the same answer as a nonexistent one, so ids can't be probed.
  - *Effective participant* (§6.2) means a trip-level participant, or a person added to any
    leg by an include override. The author of a contributed leg (`participant_scope = author`)
    is on that leg, but that alone doesn't share the trip; it only matters once the author is
    no longer a participant (Q-16).
  - Removing a participant removes their per-leg overrides on that trip too, so a leftover leg
    include can't keep sharing the trip with them. Legs they contributed stay theirs.
  - The Admin edits only trips they can see, so they can't make a trip invisible to
    themselves (RLS checks the updated row against the read policy too; the policy mirrors it).
  - Responses name other accounts by directory id and display name only; no trips response
    contains anyone's email or OIDC identity (each response is scanned in the tests). Sharing
    settings go only to core editors (the unlisted slug is a capability URL).
  - Tests: `tests/permissions/test_trips_api.py` (every endpoint × every actor, plus what each
    actor sees), `test_trip_guards.py` (the reference triggers as `travel_app`), and the matrix
    (65 actions × 7 actors).

### 6.4 Row-level security policies

Every table with an owner/author column has RLS enabled. A test enumerates all tables in the
schema and fails if any user-owned table lacks RLS or a policy for each command.

| Table group | SELECT | INSERT | UPDATE | DELETE |
|---|---|---|---|---|
| `location_point`, `timeline_segment`, `raw_file`, `import_batch`, `coverage_report`, `detection_run`, `rejected_candidate`, `device_token`, `push_subscription`, `integration_setting`, `user_preference`, `tag` | `owner = app.user_id()` | same | same (points/raw files: never, trigger) | owner (points: purge only) |
| `trip` | `app.can_view_trip(id)` | `owner = me AND app.can_create()` | `app.can_edit_trip_core(id)` | `owner = me` |
| `leg`, `route` | `app.can_view_trip(trip)` | core editor, or contributor with `author = me` | core editor on core legs, author on own (while they may contribute) | same as update |
| `trip_participant` | view trip | core editor, and the person is visible to them | core editor; own `public_consent` via function; the person stays visible | core editor |
| `leg_participant_override` | view trip | core editor, or a person I manage who may contribute; the person visible to me | same | same |
| `trip_note`, `media`, `trip_tag`, `track_contribution` | view trip | contributor and `author = me` | `author = me` | `author = me` |
| `vehicle`, `vehicle_ownership` | `app.can_view_vehicle(v)` | any member | `app.can_manage_vehicle(v)` | managing user |
| `vehicle_private` | managing user | managing user | managing user | managing user |
| `home_period` | `managed_by = me OR (shared_with_family AND app.is_family())` | `managed_by = me` | `managed_by = me` | `managed_by = me` |
| `person` | `visibility = family` or creator or linked user or on a trip I can view | any member | managing user or Admin | managing user |
| `user` | own row (active) or Admin or `auth` context; family reads `accounts_userdirectory` (id, display name, person, active; `app.is_family()`) | `auth` context or Admin | own row, Admin, `auth` context (guard triggers: role, identity, active flag) | none (deactivate instead) |
| `access_request`, `allowlist_entry`, `invite`, `audit_log` | Admin | via public endpoint function / Admin | Admin | Admin |
| reference datasets | everyone (no RLS) | owner role only | owner role only | owner role only |

**Implementation notes (milestone 1.3).** Policies are in `backend/travel/core/migrations/0002_row_level_security.py`;
helpers live in schema `app` and are executable only by `travel_app`. Guard triggers enforce
column rules RLS cannot: only the Admin changes roles or (de)activates accounts; identity fields
change only at login; trip owners change only through a transfer; leg author/trip/contribution
status are fixed; only a participant (or their managing user) sets their public consent;
contributions keep their author. Account privacy (D-76) is `core` migration 0002 tightened by
`accounts/migrations/0003_user_directory.py`; the only view `travel_app` may read is listed in
`db_privileges.APP_READABLE_VIEWS`. Every request runs in one transaction with
`app.user_id` set by `RlsContextMiddleware`; workers use `rls_context(user_id)`.

**Trips API (work-order item 6).** `trips/migrations/0003_trip_api_guards.py` adds the person
visibility checks above, makes deleting a contributed leg need the same right as editing it
(the author, while they may still contribute), and adds triggers for references, which
foreign keys check without RLS: a trip's purpose belongs to its owner and its cover photo to the
trip; a leg's stops belong to its trip and its current route is one of its own versions (these
apply to every role); a leg takes only a vehicle the acting user can see (owner role exempt).
Each fires only when the column is set or changed, so an existing reference never blocks an
unrelated edit.

**Performance notes (milestone 2.3).** Policies on large tables write the role check as
`(SELECT app.is_family())`, so PostgreSQL computes it once per statement (an InitPlan) instead of
once per row; same rule, `history/migrations/0007_rls_once_per_statement.py` (points, segments,
coverage). Under RLS, a query condition is used as an index condition only if its operator is
LEAKPROOF; PostGIS operators such as `&&` are not, so spatial lookups as `travel_app` go through
leakproof bigint keys instead (§14).

### 6.5 Public pages: separate read-only path

- Publishing (or editing a public trip) enqueues `build_public_snapshot(trip_id)`. The builder
  is the **only** code that copies data into `public_trip_snapshot`, and it copies an explicit
  allowlist:
  - title
  - map: route geometries simplified and **trimmed by privacy zones**, with leg mode only for
    line styling
  - dates (local dates at the trip's precision; times only if `public_show_times`)
  - the owner's `public_description`
  - the owner's chosen images (`public_selected`), as stripped display copies
  - other participants' names, notes, photos and legs **only** where that participant set
    `public_consent`
- Nothing else is ever copied: no purpose, tags, vehicles, exact times, notes without consent,
  home data, stops' addresses, participants without consent, raw points.
- Public views are a separate Django URLconf using the `public` DB alias, which connects as
  `travel_public`. That role has `SELECT` on the snapshot tables only, so even a bug in a public
  view cannot read a private column.
- Unlisted pages send `X-Robots-Tag: noindex, nofollow` and `<meta name="robots" content="noindex">`;
  listed trips appear on the owner's profile only when the profile is enabled.
- Privacy zones: on by default per trip; every home period point of the owner and of consenting
  participants is buffered by `privacy_zone_radius_m` (default 1 km) and the route is clipped
  with `ST_Difference`. This removes the start and end near home, and any other pass near a home.
- Rate limiting per IP on all public routes (PostgreSQL-backed counters) plus Cloudflare at the edge.
- **Leak tests:** fixtures fill every private field with a unique sentinel string, publish the
  trip, render every public page and endpoint, and assert no sentinel appears; a schema test
  asserts the snapshot tables contain only allowlisted columns.

### 6.6 Participant consent for public pages

Each participant controls their own `public_consent` (per trip, covering their name, their notes,
photos and legs; each note and photo also has its own flag). For persons without an account,
the managing user decides (decision D-21, Open question Q-7).

### 6.7 Honesty notice

Shown at first login and on the privacy page, and acknowledged once (`privacy_notice_ack_at`):
"Privacy here is enforced by the app. The server's operator (Adam) has technical access to the
database and backups and could read anything stored here, including your raw location history."
