# Backups: what you (Adam) need to set up

The app server writes **encrypted** backups into an outbox; the NAS **pulls** them and keeps its
own versioned snapshots. The server holds no credentials for the NAS, so a compromised server
cannot delete or encrypt your backup history. Design: PLAN.md §22.

## 1. Create the backup key — on your laptop, not on the server

```bash
age-keygen -o travel-backup.key        # install age from your OS package manager
grep 'public key' travel-backup.key    # -> age1...
```

- Put the **public** key (`age1…`) into the server's `.env` as `AGE_RECIPIENT=age1...`, then
  `docker compose -f compose.yaml -f compose.dev.yaml up -d backup` (or `./dev up`).
- Store `travel-backup.key` (the **private** key) in your password manager **and** on paper or
  an offline drive. Without it the backups are unreadable — by design, including for the server.
- Until `AGE_RECIPIENT` is set, the nightly job logs a warning and writes nothing.

Check it works: `./dev backup-now`, then look in `/storage/hdd1/travel-history/backup-outbox/`.

## 2. Let the NAS read the outbox (read-only, nothing else)

This changes the server's SSH configuration, so it's yours to apply. On the **NAS**, create a
key for the pull job:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/travel-backup-pull -N '' -C travel-backup-pull
```

On the **server**, append one line to `~adam/.ssh/authorized_keys` (one line, edit the key):

```
command="/usr/bin/rrsync -ro /storage/hdd1/travel-history/backup-outbox",restrict ssh-ed25519 AAAA...nas-public-key... travel-backup-pull
```

`rrsync -ro` confines that key to read-only rsync of the outbox; `restrict` disables shells,
port forwarding and PTYs. (`rrsync` ships with Ubuntu's `rsync` package.)

## 3. Pull and snapshot on the NAS (nightly, after 03:30 server time)

```bash
#!/bin/sh
# /usr/local/bin/travel-backup-pull.sh on the NAS, run from cron at ~05:00
set -eu
DEST=/volume1/backups/travel-history/current      # adjust to your NAS
rsync -a --partial -e "ssh -i ~/.ssh/travel-backup-pull" \
  adam@<server-lan-address>: "$DEST"/
# Then take a read-only snapshot of $DEST, e.g.
#   ZFS:    zfs snapshot pool/backups@travel-$(date +%F)
#   btrfs:  btrfs subvolume snapshot -r /volume1/backups /volume1/.snapshots/travel-$(date +%F)
#   Synology: schedule Snapshot Replication on the shared folder
#   other:  restic backup "$DEST" (restic repository on the NAS)
```

- No `--delete`: the server prunes old database dumps locally (keeps 7); the NAS keeps them.
- Keep at least 30 daily + 12 monthly snapshots.

## 4. Offline copy checklist

- [ ] Every original Timeline export also lives on an offline drive (not permanently attached),
      refreshed after each new export.
- [ ] The private key and a copy of `.env` are in your password manager and on offline media.
- [ ] Twice a year: test a restore from the NAS copy (`docs/restore.md`).

## Risks of home-only backups

Fire, flood, theft or a power surge can take out the server and the NAS together, and
ransomware that obtains the NAS admin password could reach the snapshots. Mitigations: the
offline drive stored away from home, and optionally an extra off-site copy later — the outbox is
already encrypted, so any cheap object storage would do.
