"""A per-day and per-year map-cell roll-up of location points (work-order item 5a, PLAN.md §14).

Whole-history map tiles at low zoom read every point of the user: 1-2 s per tile at 3.6 M points
(docs/design/resource-budget.md §21.1). `history_pointrollup` counts points per owner, map cell
(the point's `tile_key` cut to zoom 8, 10, ..., 20), UTC day and UTC year, and source, so such a
tile reads a few thousand roll-up rows instead.

Statement-level triggers keep it equal to the raw points in the same transaction: an INSERT adds
the inserted rows (`ON CONFLICT DO NOTHING` duplicates are not in the transition table), a DELETE
subtracts the deleted ones and removes rows that reach zero. Points are append-only (no UPDATE),
and a re-import never deletes (rule 6), so these two events are the only ways the counts change.
The triggers run with the caller's rights: as `travel_app` the roll-up's own policies apply, and
a point's owner is already checked by the point policies. Upserts go in key order so concurrent
writers of one owner take row locks in the same order; tracker and import points never share a
row anyway (the source is part of the key). TRUNCATE is not mirrored (only test teardown uses it,
and it truncates every table).

The SQL here and travel/history/tiles.py (ROLLUP_LEVELS, the grains) must agree; tests check it.
"""


import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


LEVELS = "{8,10,12,14,16,18,20}"
OWN = "owner_id = app.user_id() AND (SELECT app.is_family())"

# Every (owner, level, grain, period, source, cell) group of a set of points, with its count.
GROUPS = f"""
SELECT k.owner_id, k.level, k.grain, k.period, k.source, k.cell, count(*)::int AS n
  FROM (SELECT p.owner_id, l.level, g.grain,
               CASE g.grain WHEN 1 THEN (p.ts AT TIME ZONE 'UTC')::date
                            ELSE date_trunc('year', p.ts AT TIME ZONE 'UTC')::date END AS period,
               p.source, p.tile_key >> (2 * (20 - l.level)) AS cell
          FROM POINTS p
         CROSS JOIN unnest('{LEVELS}'::smallint[]) AS l(level)
         CROSS JOIN (VALUES (1::smallint), (2::smallint)) AS g(grain)) k
 GROUP BY 1, 2, 3, 4, 5, 6
"""

KEY = (
    "r.owner_id = d.owner_id AND r.level = d.level AND r.grain = d.grain AND r.cell = d.cell"
    " AND r.period = d.period AND r.source = d.source"
)

FORWARD = f"""
ALTER TABLE history_pointrollup ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_all ON history_pointrollup FOR ALL TO travel_app
  USING ({OWN}) WITH CHECK ({OWN});

CREATE FUNCTION history_point_rollup_add() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO history_pointrollup AS r (owner_id, level, grain, period, source, cell, n)
  SELECT d.* FROM ({GROUPS.replace("POINTS", "new_points")}) d
   ORDER BY d.owner_id, d.level, d.grain, d.cell, d.period, d.source
  ON CONFLICT ON CONSTRAINT pointrollup_key DO UPDATE SET n = r.n + EXCLUDED.n;
  RETURN NULL;
END $$;

CREATE FUNCTION history_point_rollup_subtract() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  -- Rows the deletion empties go first (n > 0 is a constraint), then the rest shrink.
  DELETE FROM history_pointrollup r
   USING ({GROUPS.replace("POINTS", "old_points")}) d
   WHERE {KEY} AND r.n <= d.n;
  UPDATE history_pointrollup r SET n = r.n - d.n
    FROM ({GROUPS.replace("POINTS", "old_points")}) d
   WHERE {KEY};
  RETURN NULL;
END $$;

CREATE TRIGGER locationpoint_rollup_add AFTER INSERT ON history_locationpoint
REFERENCING NEW TABLE AS new_points
FOR EACH STATEMENT EXECUTE FUNCTION history_point_rollup_add();

CREATE TRIGGER locationpoint_rollup_subtract AFTER DELETE ON history_locationpoint
REFERENCING OLD TABLE AS old_points
FOR EACH STATEMENT EXECUTE FUNCTION history_point_rollup_subtract();

-- Points that existed before this migration (runs as the owner role, outside RLS).
INSERT INTO history_pointrollup (owner_id, level, grain, period, source, cell, n)
SELECT * FROM ({GROUPS.replace("POINTS", "history_locationpoint")}) d;
"""

REVERSE = """
DROP TRIGGER IF EXISTS locationpoint_rollup_subtract ON history_locationpoint;
DROP TRIGGER IF EXISTS locationpoint_rollup_add ON history_locationpoint;
DROP FUNCTION IF EXISTS history_point_rollup_subtract();
DROP FUNCTION IF EXISTS history_point_rollup_add();
"""


class Migration(migrations.Migration):

    dependencies = [
        ('history', '0009_tracker_point_insert'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PointRollup',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('level', models.SmallIntegerField()),
                ('grain', models.SmallIntegerField(choices=[(1, 'Day'), (2, 'Year')])),
                ('period', models.DateField()),
                ('source', models.CharField(choices=[('owntracks', 'OwnTracks'), ('overland', 'Overland'), ('gpslogger', 'GPSLogger'), ('colota', 'Colota'), ('google_raw', 'Google raw signal'), ('google_path', 'Google timeline path'), ('gpx', 'GPX'), ('other', 'Other')], max_length=16)),
                ('cell', models.BigIntegerField()),
                ('n', models.IntegerField()),
                ('owner', models.ForeignKey(db_index=False, on_delete=django.db.models.deletion.DB_CASCADE, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('owner', 'level', 'grain', 'cell', 'period', 'source'), name='pointrollup_key'), models.CheckConstraint(condition=models.Q(('n__gt', 0)), name='pointrollup_positive')],
            },
        ),
        migrations.RunSQL(FORWARD, REVERSE),
    ]
