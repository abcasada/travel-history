# NEXT

Handoff note for the next session or subagent. Keep it short; overwrite, don't append history.

- **In flight:** item 8 (tracker exposure), dispatched to builder-xhigh to PREPARE ONLY (2026-11-17). Show Adam the proxy change and DNS record, then wait for "go". Next after that dispatch: item 3 (T5), which /bulk on the SSD (D-84) unblocks, then item 5a and item 9.
- **Blocked or deferred:** item 4 is deferred (AGE_RECIPIENT and the export); item 5a waits on item 3.
- **Host alert:** /storage/hdd1 (Hitachi /dev/sda) is failing. It was unmounted automatically on 2026-11-14 when the nightly upgrade re-executed systemd, and blkid can't read its filesystem. Adam has been given checks (blkid, smartctl, read-only mount, no fsck before copying, ddrescue) and the advice to replace it. Containers (travel-history web/worker/backup, Jellyfin, Channels DVR) still hold the stale mount. Workaround (D-84): .env TRAVEL_BULK_DIR=/home/adam/apps/travel-history/var/bulk; e2e passes, uploads included (2026-11-17).
- **Waiting on Adam:** item 8's "go" and DNS record; a new disk (then point TRAVEL_BULK_DIR back at it, move var/bulk over, recreate the containers, and run `./dev restore-test`); AGE_RECIPIENT; the Timeline export and flight spreadsheet in data/private/; an optional ORS key. All earlier questions were answered 2026-11-17.
- **Notes:** PLAN.md is an index; design in docs/design/, decisions in docs/decisions.md. `./dev test-quick` at item ends, `./dev test` at milestones.
