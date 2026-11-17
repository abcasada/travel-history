"""Hourly point counts in the roll-up, for the coverage strip (work-order item 5a).

The coverage strip counts points per *local* day; at 3.6 M points one year took about 1 s,
mostly an index scan of every point in the year. Rows with grain HOUR (3), at level 0, count an
owner's points per UTC hour and source: `period` is the UTC date and `cell` the UTC hour (0-23).
Level 0 is otherwise unused (map cells start at zoom 8), so these rows never meet the map
queries. A local day is a whole number of UTC hours whenever the zone's offsets are whole hours;
travel/history/tiles.py sums these rows then and counts points otherwise (e.g. +05:30).

Same triggers as history migration 0010, with the hour groups added; existing points are
backfilled.
"""

from django.db import migrations, models

LEVELS = "{8,10,12,14,16,18,20}"


def groups(points: str, hours: bool) -> str:
    """Every (owner, level, grain, period, source, cell) group of a set of points, with its
    count; with or without the hour groups."""
    sql = f"""
SELECT k.owner_id, k.level, k.grain, k.period, k.source, k.cell, count(*)::int AS n
  FROM (SELECT p.owner_id, l.level, g.grain,
               CASE g.grain WHEN 1 THEN (p.ts AT TIME ZONE 'UTC')::date
                            ELSE date_trunc('year', p.ts AT TIME ZONE 'UTC')::date END AS period,
               p.source, p.tile_key >> (2 * (20 - l.level)) AS cell
          FROM {points} p
         CROSS JOIN unnest('{LEVELS}'::smallint[]) AS l(level)
         CROSS JOIN (VALUES (1::smallint), (2::smallint)) AS g(grain)) k
 GROUP BY 1, 2, 3, 4, 5, 6"""
    if hours:
        sql += f"""
UNION ALL
SELECT p.owner_id, 0::smallint, 3::smallint, (p.ts AT TIME ZONE 'UTC')::date, p.source,
       extract(hour FROM p.ts AT TIME ZONE 'UTC')::bigint, count(*)::int
  FROM {points} p
 GROUP BY 1, 2, 3, 4, 5, 6"""
    return sql


KEY = (
    "r.owner_id = d.owner_id AND r.level = d.level AND r.grain = d.grain AND r.cell = d.cell"
    " AND r.period = d.period AND r.source = d.source"
)


def functions(hours: bool) -> str:
    return f"""
CREATE OR REPLACE FUNCTION history_point_rollup_add() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO history_pointrollup AS r (owner_id, level, grain, period, source, cell, n)
  SELECT d.* FROM ({groups("new_points", hours)}) d
   ORDER BY d.owner_id, d.level, d.grain, d.cell, d.period, d.source
  ON CONFLICT ON CONSTRAINT pointrollup_key DO UPDATE SET n = r.n + EXCLUDED.n;
  RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION history_point_rollup_subtract() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  -- Rows the deletion empties go first (n > 0 is a constraint), then the rest shrink.
  DELETE FROM history_pointrollup r
   USING ({groups("old_points", hours)}) d
   WHERE {KEY} AND r.n <= d.n;
  UPDATE history_pointrollup r SET n = r.n - d.n
    FROM ({groups("old_points", hours)}) d
   WHERE {KEY};
  RETURN NULL;
END $$;
"""


FORWARD = (
    functions(hours=True)
    + """
-- Points that existed before this migration (runs as the owner role, outside RLS).
INSERT INTO history_pointrollup (owner_id, level, grain, period, source, cell, n)
SELECT owner_id, 0, 3, (ts AT TIME ZONE 'UTC')::date, source,
       extract(hour FROM ts AT TIME ZONE 'UTC')::bigint, count(*)
  FROM history_locationpoint
 GROUP BY 1, 2, 3, 4, 5, 6;
"""
)

REVERSE = "DELETE FROM history_pointrollup WHERE grain = 3;" + functions(hours=False)


class Migration(migrations.Migration):
    dependencies = [("history", "0012_morton_compact_sql")]
    operations = [
        migrations.AlterField(
            model_name="pointrollup",
            name="grain",
            field=models.SmallIntegerField(choices=[(1, "Day"), (2, "Year"), (3, "Hour")]),
        ),
        migrations.RunSQL(FORWARD, REVERSE),
    ]
