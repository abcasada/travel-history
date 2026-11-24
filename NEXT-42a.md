# NEXT-42a (lane 2, branch item/42a)

Go-live hardening from 41a (docs/review/2026-11-24-go-live.md). In progress.

- Done (60b3ec8): F-1 (CSP/XFO before WhiteNoise, production_problems checks the order), F-2
  (travel.core.bodylimit, DATA_UPLOAD_MAX_MEMORY_SIZE 2.5 MiB, tracker reads its own body),
  F-7 (no docs/schema in production, signed-in session for them in dev; provider errors →
  no user, 30 s back-off, junk tokens never reach the provider), F-8 (CF-Connecting-IP with a
  non-public Host → 404, ingest-only exempt), F-9 (scope all needs issuer + client), bearer
  tokens checked for travel-users and amr (part of F-3).
- Next: F-10 (public → 422), F-11 (devcopy + e2e_cleanup), F-3 (session re-check, deactivate
  command), F-6 (digests), smoke checks, docs (D-107 onward), quick suite, golive-smoke local.
