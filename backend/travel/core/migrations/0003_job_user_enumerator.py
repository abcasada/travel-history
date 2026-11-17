"""Periodic jobs that cover every user under row-level security (work-order item 9, T8, D-87).

The worker connects as `travel_app`, which sees a user's rows only inside a transaction whose
`app.user_id` is that user. A nightly job therefore needs to learn *which* users to visit
before it can act as each of them. `app.job_user_ids` answers exactly that and nothing more:

- it returns bare account ids (SETOF bigint), no other column;
- only active accounts whose role is in `roles` (the job's audience, e.g. Admin and Member for
  raw-history maintenance);
- only in the `jobs` system context with no user set, so an ordinary request (or a job body
  already acting as a user) gets nothing. Outside that context it returns no rows (fail closed,
  like the policies).

It is SECURITY DEFINER (owned by `travel_owner`, so it reads `accounts_user` without the row
policy) with a pinned search_path. EXECUTE is revoked from PUBLIC here; `db_privileges.apply`
grants every function in schema `app` to `travel_app` after migrate, as for the policy helpers.
The `jobs` context grants nothing else: no policy mentions it.
"""

from django.db import migrations

FORWARD = r"""
CREATE FUNCTION app.job_user_ids(roles text[]) RETURNS SETOF bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT u.id FROM accounts_user u
   WHERE app.ctx() = 'jobs' AND app.user_id() IS NULL
     AND u.is_active AND u.role = ANY (roles)
   ORDER BY u.id
$$;
REVOKE ALL ON FUNCTION app.job_user_ids(text[]) FROM PUBLIC;
"""

REVERSE = "DROP FUNCTION IF EXISTS app.job_user_ids(text[]);"


class Migration(migrations.Migration):
    dependencies = [("core", "0002_row_level_security")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
