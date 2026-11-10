# Host and environment

Moved from PLAN.md §2 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 2. Host and environment

Inspected 2026-10-19 (`lscpu`, `free`, `lsblk`, `docker info`, `docker ps`):

| Item | Current host | Notes |
|---|---|---|
| CPU | Intel Xeon W3565, 4 cores / 4 threads, 3.2 GHz (2009, Nehalem) | **SSE4.2, no AVX/AVX2.** Every native binary we ship (wheels, Rust/Go tools, Valhalla) must run on x86-64-v2. Verified per image in CI-style smoke tests. |
| RAM | 11 GiB, 4 GiB swap | Shared with other apps. |
| SSD | 112 GB; root LV 55 GB (28 GB free); ~55 GB of the volume group appears unallocated (needs `sudo vgs` to confirm) | Docker root `/var/lib/docker` lives here, so DB volumes are on SSD. |
| HDD | 931 GB at `/storage/hdd1` (empty apart from `media/`, `shares/`, `backups/`) | Bulk storage: raw imports, photos, backup outbox. |
| OS / Docker | Ubuntu 26.04.1 LTS, kernel 7.0, Docker 29.8, Compose v5.6 | No `make`, `node`, `pre-commit` on the host — all tooling runs in containers via `./dev`. |
| Other apps | bible app, gas-gauge reader, pinpoint challenge, weather, flight-pricing, Home Assistant image | All bind `127.0.0.1:<port>`; each has its own compose project. |
| Public ingress | **Cloudflare Tunnel**, no local reverse proxy or TLS | A shared, dashboard-managed `cloudflared` (host networking, `~/apps/cloudflared`) plus one app that runs its own tunnel container. TLS terminates at Cloudflare. |

**Migration note.** The prompt says the server may be moving to a Ryzen 5 3600 / 32 GB machine. On
the current host the full North America Valhalla build is impossible (RAM and SSD), and the
app's 60 GB SSD budget does not fit in the 28 GB free. Development uses small data and a
Kansas extract, which fit. The design targets the Ryzen host (§21).

**How the app fits the existing ingress.** It follows the house pattern: the `web` container
publishes `127.0.0.1:8780`, and later a public hostname `travel.adamcasada.com → http://localhost:8780`
is added to the shared dashboard-managed tunnel (a change to shared infrastructure, so it waits
for approval; see the go-live checklist in §23, phase 8). Until Authentik with 2FA is live the
app is **also** bound to the server's LAN address (`TRAVEL_LAN_BIND`, set in `.env`) so it is
reachable only from the LAN and over WireGuard. No router port forwards are involved.
