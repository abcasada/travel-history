# Host and environment

Moved from PLAN.md §2 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 2. Host and environment

Inspected 2026-10-19 (`lscpu`, `free`, `lsblk`, `docker info`, `docker ps`):

| Item | Current host | Notes |
|---|---|---|
| CPU | Intel Xeon W3565, 4 cores / 4 threads, 3.2 GHz (2009, Nehalem) | **SSE4.2, no AVX/AVX2.** Every native binary we ship (wheels, Rust/Go tools, Valhalla) must run on x86-64-v2. Verified per image in CI-style smoke tests. |
| RAM | 11 GiB, 4 GiB swap | Shared with other apps. |
| SSD | 112 GB; root LV extended to 108 GB on 2026-11-10 (about 70 GB free) | Docker root `/var/lib/docker` lives here, so DB volumes are on SSD. |
| HDD | 931 GB at `/storage/hdd1` (empty apart from `media/`, `shares/`, `backups/`) | Bulk storage: raw imports, photos, backup outbox. **2026-11-11: went emergency read-only with I/O errors (Hitachi HUA721010); Adam to check or replace it.** It was unmounted 2026-11-14; until it's replaced, `/bulk` lives on the SSD (D-84). |
| OS / Docker | Ubuntu 26.04.1 LTS, kernel 7.0, Docker 29.8, Compose v5.6 | No `make`, `node`, `pre-commit` on the host — all tooling runs in containers via `./dev`. |
| Other apps | bible app, gas-gauge reader, pinpoint challenge, weather, flight-pricing, Home Assistant image | All bind `127.0.0.1:<port>`; each has its own compose project. |
| Public ingress | **Cloudflare Tunnel**, no local reverse proxy or TLS | A shared, dashboard-managed `cloudflared` (host networking, `~/infra/cloudflared`; checked 2026-11-17: no app runs its own tunnel container any more). TLS terminates at Cloudflare. |

**Migration note.** The prompt says the server may be moving to a Ryzen 5 3600 / 32 GB machine. On
the current host the full North America Valhalla build is impossible (RAM and SSD), and the
app's 60 GB SSD budget does not fit in the 28 GB free. Development uses small data and a
Kansas extract, which fit. The design targets the Ryzen host (§21).

**How the app fits the existing ingress.** It follows the house pattern (the shared tunnel lives
in `~/infra/cloudflared`; routes are listed in `~/infra/TUNNELS.md`): the production stack's
`web` container publishes `127.0.0.1:8784` only, and at go-live (item 40e) the public hostname
`travel.adamcasada.com → http://localhost:8784` is pointed at it; `trips.adamcasada.com`
redirects there (D-96, [production guide](../production.md)). Before go-live, the same hostname
routes only the tracker paths to the production `ingest` service on `127.0.0.1:8783` (work-order
item 8, D-85, [exposure guide](../tracking/exposure.md)); adding a route is a
shared-infrastructure change that Adam makes after approving it. The development stack is a
separate compose project on `127.0.0.1:8780` **and** the server's LAN address
(`TRAVEL_LAN_BIND`, set in `.env`), reachable only from the LAN and over WireGuard, never behind
the tunnel (D-28). No router port forwards are involved.
