# Backup image: pg_dump/pg_restore matching the server version, zstd and age (PLAN.md §22).
FROM postgis/postgis:18-3.6@sha256:4a43e3c3e5d55b9208240fc71db543b79c638766280c625a425bd0a2390989c4
# Debian's security updates the pinned base lags (as backend/Dockerfile).
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && apt-get install -y --no-install-recommends age zstd python3 \
 && rm -rf /var/lib/apt/lists/*
COPY backup.sh restore.sh schedule.sh verify_raw.py /backup/
RUN chmod 0755 /backup/*.sh
ENTRYPOINT []
CMD ["/backup/schedule.sh"]
