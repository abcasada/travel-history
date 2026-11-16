"""Who may add raw points, tightened for tracker ingestion (work-order item 7, PLAN.md §9.1).

Before: any active account could insert points it owns. Now an INSERT also needs:

- a role that may own data (Admin or Member). Viewers have no raw history (§6.3), so a
  Viewer's leftover device token writes nothing, and nor does any other path;
- when the point names a device, a token of the same owner that is not revoked. The tracker
  endpoint already resolves the token and acts as its owner; this makes "a token writes only
  into its owner's history, and only until it is revoked" hold in the database too. A foreign
  key alone would not: foreign-key checks ignore row-level security.

`app.can_create()` stays in a scalar sub-select (an InitPlan, computed once per statement,
history migration 0007). The device check depends on the row; it runs only for points that
name a device (tracker points), not for Timeline imports.
"""

from django.db import migrations

FORWARD = r"""
CREATE FUNCTION app.owns_live_device(d bigint) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT EXISTS (SELECT 1 FROM accounts_devicetoken
                  WHERE id = d AND user_id = app.user_id() AND revoked_at IS NULL)
$$;

ALTER POLICY own_insert ON history_locationpoint
  WITH CHECK (owner_id = app.user_id() AND (SELECT app.can_create())
              AND (device_id IS NULL OR app.owns_live_device(device_id)));
"""

REVERSE = r"""
ALTER POLICY own_insert ON history_locationpoint
  WITH CHECK (owner_id = app.user_id() AND (SELECT app.is_family()));
DROP FUNCTION IF EXISTS app.owns_live_device(bigint);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_device_token_guards"),
        ("history", "0008_point_tile_key"),
    ]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
