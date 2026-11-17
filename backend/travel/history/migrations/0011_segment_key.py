"""A btree-indexable spatial key for Timeline segments (work-order item 5a, PLAN.md §14).

Segment tiles scanned the user's whole history: under RLS the GiST index on `geom` is unusable
(PostGIS's `&&` is not LEAKPROOF; history migration 0008). Points are single positions and get a
tile key; segments have extents, so `seg_key` is a quadtree key: the smallest Web Mercator tile
(zoom 0..20) that holds the whole bounding box, as its zoom-20 Morton prefix shifted left by
5 bits, ORed with that zoom. Quadtree tiles are either nested or disjoint, so a segment can only
touch map tile T if its tile lies inside T (a key range) or contains T (one of T's ancestors, an
equality per zoom level); travel/history/tiles.py builds both. Memories have no geometry and no
key. Only current versions are drawn, so the index is partial.

The append-only trigger compares whole rows except the columns allowed to change; generated
columns are not yet computed in a BEFORE trigger, so `seg_key` is excluded like `time_range`.
"""


from django.conf import settings
from django.db import migrations, models


FUNCTION = r"""
CREATE FUNCTION app.extent_key(g geometry) RETURNS bigint
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE SET search_path = public, pg_temp AS $$
DECLARE
  -- Zoom-20 tile keys of the north-west and south-east corners (app.tile_key clamps both).
  a bigint := app.tile_key(ST_Point(ST_XMin(g), ST_YMax(g)));
  b bigint := app.tile_key(ST_Point(ST_XMax(g), ST_YMin(g)));
  s int := 0;
BEGIN
  IF a IS NULL OR b IS NULL THEN
    RETURN NULL;  -- empty geometry
  END IF;
  -- Both corners in one tile means the whole box is: drop x/y bit pairs until they agree.
  WHILE (a >> s) <> (b >> s) LOOP
    s := s + 2;
  END LOOP;
  RETURN (((a >> s) << s) << 5) | (20 - s / 2);
END
$$;
"""

POINTER_ONLY = r"""
CREATE OR REPLACE FUNCTION history_segment_pointer_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF (to_jsonb(NEW) - 'is_current' - 'superseded_by_id' - 'time_range' - 'seg_key')
     IS DISTINCT FROM
     (to_jsonb(OLD) - 'is_current' - 'superseded_by_id' - 'time_range' - 'seg_key') THEN
    RAISE EXCEPTION 'timeline segment versions are append-only; only is_current/superseded_by may change'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END $$;
"""

POINTER_ONLY_BEFORE = r"""
CREATE OR REPLACE FUNCTION history_segment_pointer_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF (to_jsonb(NEW) - 'is_current' - 'superseded_by_id' - 'time_range')
     IS DISTINCT FROM
     (to_jsonb(OLD) - 'is_current' - 'superseded_by_id' - 'time_range') THEN
    RAISE EXCEPTION 'timeline segment versions are append-only; only is_current/superseded_by may change'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('history', '0010_point_rollup'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunSQL(FUNCTION, "DROP FUNCTION app.extent_key(geometry);"),
        migrations.AddField(
            model_name='timelinesegment',
            name='seg_key',
            field=models.GeneratedField(db_persist=True, expression=models.Func(models.F('geom'), function='app.extent_key', output_field=models.BigIntegerField()), output_field=models.BigIntegerField()),
        ),
        migrations.AddIndex(
            model_name='timelinesegment',
            index=models.Index(condition=models.Q(('is_current', True)), fields=['owner', 'seg_key'], name='segment_owner_key_idx'),
        ),
        migrations.RunSQL(POINTER_ONLY, POINTER_ONLY_BEFORE),
    ]
