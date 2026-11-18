#!/usr/bin/env bash
# Builds Valhalla routing tiles from one OSM extract (runs inside the pinned Valhalla image as a
# non-root user; see valhalla/compose.yaml and docs/valhalla.md).
#
# Layout under /data (valhalla/data on the host, git-ignored):
#   pbf/<name>.osm.pbf        the downloaded extract (kept for rebuilds)
#   builds/<UTC timestamp>/   one complete build: valhalla.json, tiles.tar, admins + time zones
#   current -> builds/<...>   what the service loads; switched only after a build succeeds
set -euo pipefail

url="${VALHALLA_PBF_URL:?set VALHALLA_PBF_URL}"
threads="${VALHALLA_BUILD_THREADS:-2}"
data=/data
pbf="$data/pbf/$(basename "$url")"
mkdir -p "$data/pbf" "$data/builds"

step() { echo; echo "== $(date -u +%H:%M:%S) $*"; }

# Peak anonymous memory (what the build really needs; memory.peak also counts page cache).
cg=/sys/fs/cgroup
anon_peak_file=$(mktemp)
( peak=0; while sleep 1; do
    a=$(awk '$1=="anon"{print $2}' "$cg/memory.stat" 2>/dev/null || echo 0)
    if [ "${a:-0}" -gt "$peak" ]; then peak=$a; echo "$peak" > "$anon_peak_file"; fi
  done ) &
sampler=$!
trap 'kill $sampler 2>/dev/null || true' EXIT

started=$SECONDS
if [ "${VALHALLA_SKIP_DOWNLOAD:-0}" != "1" ]; then
  step "download $url"
  part="$pbf.part"; rm -f "$part"
  since=(); [ -f "$pbf" ] && since=(-z "$pbf")
  curl -fL --retry 3 --remote-time "${since[@]}" -o "$part" "$url"
  if [ -s "$part" ]; then
    # Geofabrik publishes <file>.md5 next to every extract.
    expected=$(curl -fsL "$url.md5" | awk '{print $1}')
    actual=$(md5sum "$part" | awk '{print $1}')
    if [ -n "$expected" ] && [ "$expected" != "$actual" ]; then
      echo "ERROR: md5 mismatch for $url (expected $expected, got $actual)" >&2; rm -f "$part"; exit 1
    fi
    mv -f "$part" "$pbf"
  else
    rm -f "$part"; echo "extract unchanged since the last download"
  fi
fi
[ -s "$pbf" ] || { echo "ERROR: no extract at $pbf" >&2; exit 1; }
download_s=$((SECONDS - started))

id=$(date -u +%Y%m%dT%H%M%SZ)
b="$data/builds/$id"
mkdir -p "$b/work"
# A failed build leaves nothing behind and never touches `current`.
trap 'kill $sampler 2>/dev/null || true; [ -f "$b/BUILD_INFO.json" ] || rm -rf "$b"' EXIT
cfg="$b/valhalla.json"

step "config ($threads threads)"
# Limits (docs/design/routing.md §13.3): trace max_shape 16,000 and max_distance 200 km are the
# documented defaults the map-matching job chunks against; search radius and GPS accuracy are
# capped at 100 m. The tile cache is capped per thread so the service stays small; Meili's grid
# cache keeps its default (it bounds the candidate-search cache that large match requests grow).
valhalla_build_config \
  --mjolnir-tile-dir "$b/tiles" \
  --mjolnir-tile-extract "$b/tiles.tar" \
  --mjolnir-admin "$b/admins.sqlite" \
  --mjolnir-timezone "$b/timezones.sqlite" \
  --mjolnir-concurrency "$threads" \
  --mjolnir-max-cache-size 268435456 \
  --additional-data-elevation "" \
  --meili-grid-cache-size 100240 \
  --service-limits-trace-max-shape 16000 \
  --service-limits-trace-max-distance 200000 \
  --service-limits-trace-max-gps-accuracy 100 \
  --service-limits-trace-max-search-radius 100 \
  > "$cfg"

cd "$b/work"
step "time zones"
t=$SECONDS; valhalla_build_timezones > "$b/timezones.sqlite"; tz_s=$((SECONDS - t))
step "admins"
t=$SECONDS; valhalla_build_admins -c "$cfg" "$pbf"; admins_s=$((SECONDS - t))
step "tiles"
t=$SECONDS; valhalla_build_tiles -c "$cfg" "$pbf"; tiles_s=$((SECONDS - t))
step "tar"
t=$SECONDS; valhalla_build_extract -c "$cfg" -v; tar_s=$((SECONDS - t))
cd "$data"
tiles_dir_mb=$(du -sm "$b/tiles" | awk '{print $1}')
# The service reads the tar; the loose tiles would double the disk use.
rm -rf "$b/tiles" "$b/work"

anon_peak=$(cat "$anon_peak_file" 2>/dev/null || echo 0)
mem_peak=$(cat "$cg/memory.peak" 2>/dev/null || echo 0)
cat > "$b/BUILD_INFO.json" <<EOF
{
  "valhalla_version": "$(valhalla_service --version | tr -d '\n' | awk '{print $NF}')",
  "extract": "$(basename "$pbf")",
  "extract_url": "$url",
  "extract_md5": "$(md5sum "$pbf" | awk '{print $1}')",
  "extract_last_modified": "$(date -u -r "$pbf" +%Y-%m-%dT%H:%M:%SZ)",
  "built_at": "$id",
  "threads": $threads,
  "seconds": {"download": $download_s, "timezones": $tz_s, "admins": $admins_s, "tiles": $tiles_s, "tar": $tar_s},
  "peak_anon_mib": $((anon_peak / 1048576)),
  "peak_cgroup_mib": $((mem_peak / 1048576)),
  "tiles_dir_mib": $tiles_dir_mb,
  "build_dir_mib": $(du -sm "$b" | awk '{print $1}'),
  "extract_mib": $(du -sm "$pbf" | awk '{print $1}')
}
EOF

step "switch current -> builds/$id"
ln -sfn "builds/$id" "$data/current.new"
mv -Tf "$data/current.new" "$data/current"
# Keep the new build and the one before it (rollback); drop older ones.
ls -1d "$data"/builds/*/ | sort | head -n -2 | xargs -r rm -rf

cat "$b/BUILD_INFO.json"
echo "total ${SECONDS}s. Restart the service to load it: ./dev valhalla up"
