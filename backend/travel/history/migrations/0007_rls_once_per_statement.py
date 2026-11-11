"""Same rules, evaluated once per statement instead of once per row (milestone 2.3).

`app.is_family()` looks up the caller's account through a SECURITY DEFINER function, which the
planner can neither inline nor hoist out of an RLS qual, so it ran for every point scanned
(about 4 s per 300k points on the current host). Wrapped in a scalar sub-select it becomes an
InitPlan: computed once, then compared per row. `app.user_id()` is a plain inlinable SQL
function and stays as it is (it also lets the planner use the (owner, ts) index).

The conditions are unchanged - only how often they are computed - so the permission matrix
and the RLS tests apply as before.
"""

from django.db import migrations

ONCE = "owner_id = app.user_id() AND (SELECT app.is_family())"
PER_ROW = "owner_id = app.user_id() AND app.is_family()"


def _sql(cond: str) -> str:
    return f"""
ALTER POLICY own_select ON history_locationpoint USING ({cond});
ALTER POLICY own_insert ON history_locationpoint WITH CHECK ({cond});
ALTER POLICY own_delete ON history_locationpoint USING ({cond});
ALTER POLICY own_all ON history_timelinesegment USING ({cond}) WITH CHECK ({cond});
ALTER POLICY own_all ON history_coveragereport USING ({cond}) WITH CHECK ({cond});
"""


class Migration(migrations.Migration):
    dependencies = [("history", "0006_place_hint_rls")]
    operations = [migrations.RunSQL(_sql(ONCE), _sql(PER_ROW))]
