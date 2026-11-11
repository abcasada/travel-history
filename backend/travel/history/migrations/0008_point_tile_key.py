"""A btree-indexable spatial key for location points (milestone 2.3, map tiles).

Under RLS, PostgreSQL only uses a query condition as an index condition if its operator is
LEAKPROOF (or the condition comes from the policy itself). PostGIS's `&&` is not, so the GiST
index on `geom` is unusable for `travel_app` and every map tile scanned the user's whole history.
bigint comparisons are leakproof: `tile_key` is the point's Web Mercator tile at zoom 20 with x
and y bits interleaved (Morton / Z-order), so every map tile at zoom <= 20 is one contiguous key
range, served by the (owner_id, tile_key) index. `travel/history/tiles.py` computes the ranges;
the bit layout here and there must match (tests compare them).
"""

from django.conf import settings
from django.db import migrations, models

FUNCTION = r"""
CREATE FUNCTION app.tile_key(g geometry) RETURNS bigint
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE SET search_path = public, pg_temp AS $$
DECLARE
  lat double precision := least(greatest(ST_Y(g), -85.0511287798), 85.0511287798);
  x bigint := least(greatest(floor((ST_X(g) + 180) / 360 * 1048576), 0), 1048575);
  y bigint := least(greatest(
      floor((1 - ln(tan(radians(lat)) + 1 / cos(radians(lat))) / pi()) / 2 * 1048576),
      0), 1048575);
BEGIN
  -- Spread the 20 bits of x and y apart, then interleave them: y in the odd bits.
  x := (x | (x << 16)) & 0x0000FFFF0000FFFF;
  x := (x | (x << 8)) & 0x00FF00FF00FF00FF;
  x := (x | (x << 4)) & 0x0F0F0F0F0F0F0F0F;
  x := (x | (x << 2)) & 0x3333333333333333;
  x := (x | (x << 1)) & 0x5555555555555555;
  y := (y | (y << 16)) & 0x0000FFFF0000FFFF;
  y := (y | (y << 8)) & 0x00FF00FF00FF00FF;
  y := (y | (y << 4)) & 0x0F0F0F0F0F0F0F0F;
  y := (y | (y << 2)) & 0x3333333333333333;
  y := (y | (y << 1)) & 0x5555555555555555;
  RETURN (y << 1) | x;
END
$$;

-- The inverse for one axis: tile x of a (shifted) key is app.morton_compact(key), tile y is
-- app.morton_compact(key >> 1). Map tiles use it to place grid cells.
CREATE FUNCTION app.morton_compact(v bigint) RETURNS bigint
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE AS $$
BEGIN
  v := v & 0x5555555555555555;
  v := (v | (v >> 1)) & 0x3333333333333333;
  v := (v | (v >> 2)) & 0x0F0F0F0F0F0F0F0F;
  v := (v | (v >> 4)) & 0x00FF00FF00FF00FF;
  v := (v | (v >> 8)) & 0x0000FFFF0000FFFF;
  v := (v | (v >> 16)) & 0x00000000FFFFFFFF;
  RETURN v;
END
$$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_user_directory'),
        ('history', '0007_rls_once_per_statement'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunSQL(
            FUNCTION,
            "DROP FUNCTION app.tile_key(geometry); DROP FUNCTION app.morton_compact(bigint);",
        ),
        migrations.AddField(
            model_name='locationpoint',
            name='tile_key',
            field=models.GeneratedField(db_persist=True, expression=models.Func(models.F('geom'), function='app.tile_key', output_field=models.BigIntegerField()), output_field=models.BigIntegerField()),
        ),
        migrations.AddIndex(
            model_name='locationpoint',
            index=models.Index(fields=['owner', 'tile_key'], name='point_owner_tile_idx'),
        ),
    ]
