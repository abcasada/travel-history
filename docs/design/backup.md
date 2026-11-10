# Backup, restore, export

Moved from PLAN.md §22 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 22. Backup, restore, export

### 22.1 Design

- **Nightly** (`backup` container, 03:30): `pg_dump -Fc` (as `travel_owner`) → `zstd` → `age`
  encrypted to the backup **public** key → `/bulk/backup-outbox/db/YYYY-MM-DD.dump.zst.age`.
  The server keeps the last 7 locally.
- **Raw files and photos** are immutable, so each is encrypted once into
  `/bulk/backup-outbox/raw/<sha256>.zst.age` and `/bulk/backup-outbox/media/<id>-<variant>.age`
  (incremental by existence check). A manifest (`manifest-YYYY-MM-DD.json`, encrypted too) lists
  every object with its checksum.
- **Pull model:** the NAS runs `rsync` over SSH with a forced-command, read-only key
  (`rrsync -ro /storage/hdd1/travel-history/backup-outbox`) and then snapshots its copy (ZFS/btrfs
  snapshots or `restic` on the NAS). The app server holds no credentials for the NAS and cannot
  delete or alter snapshots. Configuring the NAS is shared infrastructure: instructions in
  `docs/backup-nas.md`, applied by Adam.
- The age **private** key never lives on the server: printed/stored offline and in a password
  manager.

### 22.2 Restore (tested)

`./dev restore-test` (part of the phase-1 acceptance): generates a throwaway age key, runs a real
backup with it, restores into a scratch PostGIS container initialized by `db/init`, compares the row
count of every table plus the RLS policy and `app` function counts with the source, and verifies
each raw file's checksum after decryption and decompression. Real restore runbook in
`docs/restore.md`: provision host → clone repo → restore `.env` from password manager → start
`db` → decrypt and `pg_restore` → copy raw/media back → `./dev up`.

### 22.3 Offline copy checklist (for Adam)

- [ ] Keep every original Timeline export on an offline drive (not permanently connected),
      refreshed after each export.
- [ ] Keep the age private key and `.env` in the password manager and on paper/offline media.
- [ ] Twice a year, do a test restore from the NAS copy.

**Risks of home-only backups:** fire, flood, theft or a power surge can take out the server and
the NAS together; ransomware with LAN access could reach the NAS if its admin credentials are
exposed. Mitigation: the offline drive stored elsewhere (family member's house, work), and
optionally an encrypted off-site copy later (the data is already age-encrypted, so any cheap
object storage would do).

### 22.4 Per-user export

A job builds a zip of everything the user owns: trips/legs/routes as GeoJSON and GPX, CSV
tables (trips, legs, flights, vehicles, home periods, tags), raw points as GeoJSON-seq/CSV,
the original uploaded files byte-for-byte, and basic photos. Download link expires after 24 h.
