"""Faster cell placement for map tiles (work-order item 5a).

`app.morton_compact()` (history migration 0008) was PL/pgSQL, which the planner can't inline:
about 1 µs per call, two calls per grid cell, and a whole-history z13 tile has tens of thousands
of cells. This version is one SQL expression over a 256-entry lookup table (each byte of the key
holds 4 x bits; every term is parenthesised because `|` and `<<` share one precedence level in
PostgreSQL), so it is inlined and runs as plain integer arithmetic. Same results (a test
compares them).
"""

from django.db import migrations

LUT = """'{0,1,0,1,2,3,2,3,0,1,0,1,2,3,2,3,4,5,4,5,6,7,6,7,4,5,4,5,6,7,6,7,
    0,1,0,1,2,3,2,3,0,1,0,1,2,3,2,3,4,5,4,5,6,7,6,7,4,5,4,5,6,7,6,7,
    8,9,8,9,10,11,10,11,8,9,8,9,10,11,10,11,12,13,12,13,14,15,14,15,12,13,12,13,14,15,14,15,
    8,9,8,9,10,11,10,11,8,9,8,9,10,11,10,11,12,13,12,13,14,15,14,15,12,13,12,13,14,15,14,15,
    0,1,0,1,2,3,2,3,0,1,0,1,2,3,2,3,4,5,4,5,6,7,6,7,4,5,4,5,6,7,6,7,
    0,1,0,1,2,3,2,3,0,1,0,1,2,3,2,3,4,5,4,5,6,7,6,7,4,5,4,5,6,7,6,7,
    8,9,8,9,10,11,10,11,8,9,8,9,10,11,10,11,12,13,12,13,14,15,14,15,12,13,12,13,14,15,14,15,
    8,9,8,9,10,11,10,11,8,9,8,9,10,11,10,11,12,13,12,13,14,15,14,15,12,13,12,13,14,15,14,15}'::bigint[]"""

FORWARD = f"""
CREATE FUNCTION app.morton_compact(v bigint) RETURNS bigint
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT {" | ".join(f"(({LUT})[((v >> {8 * k}) & 255) + 1] << {4 * k})" for k in range(8))}
$$;
"""

REVERSE = r"""
DROP FUNCTION app.morton_compact(bigint);
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
    dependencies = [("history", "0011_segment_key")]

    # Drop and create (not REPLACE): the language and strictness change.
    operations = [
        migrations.RunSQL("DROP FUNCTION app.morton_compact(bigint);" + FORWARD, REVERSE),
    ]
