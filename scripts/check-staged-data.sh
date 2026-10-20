#!/usr/bin/env bash
# Refuses commits that would put personal data in git.
# Rules (see CLAUDE.md "Standing rules"):
#   - nothing under data/private/
#   - no file larger than 2 MB (real exports are big; fixtures are small)
#   - location-history-like files (Timeline JSON, GPX, KML, OwnTracks dumps) only under a
#     fixtures directory, and they must carry the SYNTHETIC marker in their content.
set -euo pipefail
fail=0
max_bytes=$((2 * 1024 * 1024))
while IFS= read -r -d '' path; do
  [ -e "$path" ] || continue   # deleted files
  case "$path" in
    data/private/*) echo "BLOCKED: $path is under data/private/ (personal data)"; fail=1; continue ;;
  esac
  size=$(git cat-file -s ":$path" 2>/dev/null || echo 0)
  if [ "$size" -gt "$max_bytes" ]; then
    echo "BLOCKED: $path is $size bytes (> 2 MB). Real exports and binaries do not belong in git."; fail=1
  fi
  case "$path" in
    *.gpx|*.kml|*.kmz|*.geojson|*.json|*.csv|*.rec)
      if git show ":$path" | head -c 200000 | grep -qE '"semanticSegments"|"rawSignals"|"timelinePath"|"latitudeE7"|<trkpt|"_type" *: *"location"'; then
        case "$path" in
          */fixtures/*|data/fixtures/*)
            if ! git show ":$path" | head -c 4096 | grep -q 'SYNTHETIC'; then
              echo "BLOCKED: $path looks like location history but lacks the SYNTHETIC marker in its first 4 KB."; fail=1
            fi ;;
          *) echo "BLOCKED: $path looks like location history and is not in a fixtures directory."; fail=1 ;;
        esac
      fi ;;
  esac
done < <(git diff --cached --name-only -z --diff-filter=ACMR)
if [ "$fail" -ne 0 ]; then
  echo "pre-commit: personal-data guard failed. Move real data to data/private/ (git-ignored)." >&2
  exit 1
fi
