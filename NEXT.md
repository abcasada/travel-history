# NEXT

Handoff note for the next session or subagent. Keep it short; overwrite, don't append history.

- **In flight:** nothing. Items 1, 2, 5, 6 and 7 are done and verified (2026-11-16).
- **Next:** item 8 (tracker exposure). Dispatch builder-xhigh to *prepare* only: production settings, a proxy/tunnel change routing only the two ingest paths, and the exact DNS record. It must not apply anything. Item 7's report lists what's needed: TRACKER_BASE_URL, DJANGO_BEHIND_TLS_PROXY, HSTS, allowed hosts, DEBUG off, RATELIMIT_CLIENT_IP_HEADER=CF-Connecting-IP only if all traffic goes through the tunnel, rebuild the production image, and disclose that Cloudflare sees tokens and payloads. Then show Adam the change and wait for "go". Meanwhile item 9 (T8) can proceed.
- **Blocked or deferred:** item 3 is blocked (HDD); item 4 is deferred (AGE_RECIPIENT, export, disk); item 5a waits on item 3.
- **Host alert:** /storage/hdd1 (Hitachi /dev/sda) is failing. It was unmounted automatically on 2026-11-14 when the nightly upgrade re-executed systemd, and blkid can't read its filesystem. Adam has been given checks (blkid, smartctl, read-only mount, no fsck before copying, ddrescue) and the advice to replace it. Containers (travel-history web/worker/backup, Jellyfin, Channels DVR) still hold the stale mount. After a new disk: recreate /storage/hdd1/travel-history/{raw,media,uploads,backup-outbox} and run `./dev restore-test`.
- **Waiting on Adam (recommended default in brackets):**
  - Approve D-81, the trips API rules [yes]; D-82, the tracker ingestion rules [yes].
  - Q-16: the owner may delete a removed participant's leg [yes]. Q-17: GPSLogger gets copyable fields plus a token QR, with no hosted profile URL [yes].
  - Confirm the D-76 directory fields (person link, active flag) [yes]. Record item 5's tile_key and InitPlan RLS as a decision [yes].
  - Q-10: Resend [yes]. Q-12: keep gitleaks [yes].
  - Disk fix; AGE_RECIPIENT; Timeline export and flight spreadsheet in data/private/; optional ORS key.
- **Notes:** PLAN.md is an index; design in docs/design/, decisions in docs/decisions.md. `./dev test-quick` at item ends, `./dev test` at milestones.
