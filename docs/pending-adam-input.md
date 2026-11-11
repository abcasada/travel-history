# Adam's input waiting to be applied

The orchestrator applies these once item 2 (in flight on 2026-11-10) lands, then deletes this file.

From Adam, 2026-11-10:
- Approved: record base-image pinning (exact version + digest, at least 14 days old) and the `./dev test-quick` / `slow` marker convention as decisions; add `./dev test-quick` to CLAUDE.md's command list.
- Q-2: the Ryzen migration is probably about 2 months out (around mid-January 2027).
- Q-3: done. The root LV is extended (108 GB, about 70 GB free). Adam wants the 1 TB HDD used for most storage. Update the environment facts in docs/ORCHESTRATION.md and docs/design/host.md.
- Q-4: Adam asked whether the Xeon can do the North America build; the orchestrator explained it.
- Q-5: the NAS isn't decided yet; keep it open.
- Q-10, Q-12: Adam asked for a recommendation; the orchestrator gave one and waits for his pick.
- Q-13: add a permissive license (MIT) so anyone can use the code; this supersedes D-43. The repo is already public, so it takes effect immediately.
- Q-15: resolved. The server is at a fixed address outside the router's DHCP range.
