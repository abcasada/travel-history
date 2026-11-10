# Backup image: pg_dump/pg_restore matching the server version, zstd and age (PLAN.md §22).
FROM postgis/postgis:18-3.6@sha256:b4466ea2ba7e3af54fcbba996d45325720f4b3ecb4f43f99b2f41367dc196f23
RUN apt-get update \
 && apt-get install -y --no-install-recommends age zstd python3 \
 && rm -rf /var/lib/apt/lists/*
COPY backup.sh restore.sh schedule.sh verify_raw.py /backup/
RUN chmod 0755 /backup/*.sh
ENTRYPOINT []
CMD ["/backup/schedule.sh"]
