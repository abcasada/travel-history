#!/usr/bin/env bash
# Realistic-size Timeline import test on the dev stack (work-order item 3, audit finding #4):
# generate a synthetic on-device export, upload it through the chunked upload API, let the worker
# archive and import it, and check that the worker's peak RSS stays under its memory limit.
#
#   ./dev import-scale-test [size_mb]   default 1024; prints results, then deletes everything
#   ./dev import-scale-test cleanup     delete the throwaway user's rows and files (after a crash)
#   KEEP=1 ./dev import-scale-test ...  keep the imported data (run cleanup yourself later)
#
# Needs about 3 × size_mb free under TRAVEL_BULK_DIR plus ~1.5 GB per GB in the database.
# Restarts the dev `worker` (resets its memory high-water mark); never touches `ingest`.
# Results land in var/scale-results/ (git-ignored). Exit status: 0 pass, 1 fail.
set -euo pipefail
cd "$(dirname "$0")/.."

compose() { docker compose -f compose.yaml -f compose.dev.yaml "$@"; }
tools() { compose run --rm -T tools python tests/scale/import_scale.py "$@"; }

if [ "${1:-}" = cleanup ]; then
  tools cleanup
  exit 0
fi

size_mb="${1:-1024}"
bulk="$(grep -E '^TRAVEL_BULK_DIR=' .env | cut -d= -f2-)"
free_mb=$(( $(df --output=avail -k "$bulk" | tail -1) / 1024 ))
need_mb=$(( size_mb * 5 + 2048 ))
echo "free under $bulk: ${free_mb} MiB (need ~${need_mb} MiB)"
[ "$free_mb" -gt "$need_mb" ] || { echo "not enough free space" >&2; exit 1; }

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="var/scale-results"
mkdir -p "$out"
export_file="/bulk/scale-test/Timeline-synthetic.json"

echo "1/4 generate ${size_mb} MB"
tools generate "$export_file" "$size_mb" | tee "$out/$stamp-generate.json"

echo "2/4 restart the worker (fresh memory high-water mark)"
compose restart worker >/dev/null
sleep 5
limit=$(compose exec -T worker cat /sys/fs/cgroup/memory.max)

# Sample the worker's cgroup every 5 s: anon memory (process RSS) vs page cache.
samples="$out/$stamp-worker-memory.tsv"
printf 'epoch\tcurrent\tanon\tfile\n' > "$samples"
(
  while :; do
    stat=$(compose exec -T worker sh -c 'cat /sys/fs/cgroup/memory.current; grep -E "^(anon|file) " /sys/fs/cgroup/memory.stat' 2>/dev/null | tr '\n' ' ') || true
    read -r cur _ anon _ file <<< "$stat" || true
    printf '%s\t%s\t%s\t%s\n' "$(date +%s)" "${cur:-}" "${anon:-}" "${file:-}" >> "$samples"
    sleep 5
  done
) &
sampler=$!
trap 'kill $sampler 2>/dev/null || true' EXIT

echo "3/4 upload, archive, import, measure"
status=0
tools run "$export_file" "/bulk/scale-test/results.json" || status=$?
kill $sampler 2>/dev/null || true

# Peak RSS of the worker processes (VmHWM survives as long as the process does).
hwm_kb=$(compose exec -T worker sh -c 'for s in /proc/[0-9]*/status; do grep -h "^VmHWM" "$s" 2>/dev/null; done' | awk '{ if ($2 > m) m = $2 } END { print m + 0 }')
cg_peak=$(compose exec -T worker cat /sys/fs/cgroup/memory.peak)
peak_anon=$(awk -F'\t' 'NR > 1 && $3 > m { m = $3 } END { print m + 0 }' "$samples")
cp "$bulk/scale-test/results.json" "$out/$stamp-results.json" 2>/dev/null || true
{
  echo "worker memory limit:        $((limit / 1048576)) MiB"
  echo "worker peak RSS (VmHWM):    $((hwm_kb / 1024)) MiB"
  echo "worker peak anon (sampled): $((peak_anon / 1048576)) MiB"
  echo "worker cgroup memory.peak:  $((cg_peak / 1048576)) MiB (includes reclaimable page cache)"
} | tee "$out/$stamp-memory.txt"

if [ "$status" -eq 0 ] && [ $((hwm_kb * 1024)) -ge "$limit" ]; then
  echo "FAIL: worker peak RSS reached its limit" >&2
  status=1
fi

if [ -z "${KEEP:-}" ]; then
  echo "4/4 cleanup"
  tools cleanup
else
  echo "4/4 KEEP set: data kept; run ./dev import-scale-test cleanup when done"
fi
echo "results: $out/$stamp-*"
[ "$status" -eq 0 ] && echo "import scale test passed" || echo "import scale test FAILED ($status)" >&2
exit "$status"
