# NEXT-43b (lane 3, branch item/43b)

Item 43b, go-live follow-ups from 42a: done, ready to merge.

- SPA: `frontend/src/auth/recheck.ts` + hook in `api/client.ts` + AuthGate note; Vitest in
  `auth/recheck.test.ts` and `App.test.tsx`. D-120.
- Lane image tags: `scripts/stack.sh` (`dev_compose` passes `lane-<item>` tags in a worktree),
  `compose.yaml` backup image uses `TRAVEL_IMAGE_TAG`, `scripts/lane.sh` (new/rm),
  `restore-test.sh`, `import-from-dev-test.sh`. D-121. Main render diff: identical except one
  added dev env line `OIDC_SESSION_RECHECK_SECONDS: "0"` on `web` (D-120).
- e2e: `./dev e2e --recheck` (`e2e/recheck.mjs`) passed in the lane with
  `OIDC_SESSION_RECHECK_SECONDS=15` (since removed from the lane .env); it fails with the
  redirect disabled.
- Orchestrator after merge: nothing to rebuild for main; `./dev lane rm 43b` now also removes
  `travel-history-backend:lane-43b` and `travel-history-backup:lane-43b`.
