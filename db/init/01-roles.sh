#!/usr/bin/env bash
# Runs once, as the PostgreSQL superuser, when the data volume is first initialized.
# Creates the three roles from PLAN.md §3/§6 and the application database, and installs the
# extensions in template1 too so test databases (created by the owner role) inherit them.
set -euo pipefail

: "${TRAVEL_OWNER_PASSWORD:?}" "${TRAVEL_APP_PASSWORD:?}" "${TRAVEL_PUBLIC_PASSWORD:?}"
DB_NAME="${TRAVEL_DB_NAME:-travel}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v owner_pw="$TRAVEL_OWNER_PASSWORD" -v app_pw="$TRAVEL_APP_PASSWORD" \
  -v public_pw="$TRAVEL_PUBLIC_PASSWORD" -v dbname="$DB_NAME" <<'SQL'
-- Owns the schema and runs migrations. CREATEDB only so the test runner can create test DBs.
CREATE ROLE travel_owner LOGIN PASSWORD :'owner_pw' CREATEDB NOSUPERUSER NOBYPASSRLS;
-- Runtime role for web + worker: owns nothing, always subject to row-level security.
CREATE ROLE travel_app LOGIN PASSWORD :'app_pw' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
-- Public renderer: can read only the public snapshot tables.
CREATE ROLE travel_public LOGIN PASSWORD :'public_pw' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
-- Lets the owner switch to the runtime roles (tests run every query as travel_app this way).
GRANT travel_app TO travel_owner;
GRANT travel_public TO travel_owner;
CREATE DATABASE :"dbname" OWNER travel_owner;
SQL

for db in template1 "$DB_NAME"; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<'SQL'
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
SQL
done
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$DB_NAME" \
  -c "REVOKE ALL ON DATABASE \"$DB_NAME\" FROM PUBLIC" \
  -c "GRANT CONNECT, TEMPORARY ON DATABASE \"$DB_NAME\" TO travel_app, travel_public"
