# NEXT-43d — flaky TitleSearch "fast typing" test

Status: done (branch item/43d, ready to merge; frontend only, no backend files touched).

- Real race found in `frontend/src/trips/useFollowedText.ts`: it kept only the last value it
  wrote, so every lagging URL value older than that looked like an outside change and reset the
  box to an old prefix. Mid-typing, that dropped the letters typed since. It now keeps a queue of
  values written and not yet seen back. A URL value that matches one is its own echo, and it and
  every older write are discarded. Any other value (Clear filters, leaving the list) replaces the text.
- `echo` (default `qEcho`) maps typed text to the form the URL reads it back in (whitespace-only
  q is not written), so a space typed over the text is no longer wiped.
- `TitleSearch.test.tsx`: the lag test runs on fake timers with synchronous fireEvent keys
  (user-event's async wrapper waits on a real timer and hangs under vitest fake timers).
  A new test covers the whitespace case. Both fail on the old hook and pass on the new one.
- Evidence: 30/30 isolated runs of the file green; `./dev test-frontend` 32 files / 193 tests;
  lint clean. HeaderSearch tests unchanged and green.
