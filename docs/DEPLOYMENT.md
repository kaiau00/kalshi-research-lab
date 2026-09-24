# Hosted research lab

**Current status — September 24, 2026:** recording and bounded paper replay continue on v6. The optional fair-value demo connector is deployed in the same service for BTC `KXBTC15M` Predictions markets. Its internal Predictions exchange-2 balance is verified at exactly $125 and the runner reports `watching`; it has submitted zero orders so far. See [DEMO_EXECUTION.md](DEMO_EXECUTION.md) for the deployment evidence and limits. Production order submission is not implemented. Settlement-window and rollover fixes passed an archive-based audit of two complete markets; independent execution checks and metadata guards are recorded in [COMMISSIONING.md](COMMISSIONING.md).

- Dashboard: https://research-lab-production-ade8.up.railway.app
- Railway service: https://railway.com/project/c6476eeb-df32-47aa-b0ef-262a50f8e9a8/service/a1bf43d4-6a8b-463a-9711-63a61e399688?environmentId=15e2863f-f700-45c7-973c-d00903bed9af
- Research source remains `7742abc`; the deployed demo connector source is `df3f4cf`. Later documentation commits need no redeployment.
- Active deployment: `62072295-2308-4b85-970b-aae1c4016ca7`, observed `SUCCESS` with a running instance.
- Dataset `/data/segments-v6`, ID `e2d5cb33e7c44660809b531f03d4b4e3`; all earlier datasets preserved.
- One replica, persistent `/data` volume and private `research-archive` bucket; HTTPS target port 8080.
- External health/readiness both 200; unauthenticated dashboard 401; authenticated status 200; both feeds connected, no recorder error.
- Existing $10 workspace hard usage limit unchanged. A full-day compact-format measurement projects approximately $8.6/month at repeated rates; growing history and future activity can change it.

The dated notes below preserve earlier commissioning history; statements about absent credentials or blocked capacity describe those earlier checks.

## Access and credentials

Dashboard username: `lab`. A generated password is saved locally in the ignored `.env.dashboard` file in the Desktop repository; it is not committed or included in Docker uploads. The same value is configured as `LAB_DASHBOARD_PASSWORD` on Railway.

The authorized key ID and base64 private key are configured as Railway secret variables. Do not commit either credential. Data/settlement and sampled execution audits passed; actual exchange multi-fill behavior and account-specific rounding remain qualified. See EXECUTION_AUDIT.md.

## Verified behavior

- External `/healthz`: 200.
- Unauthenticated dashboard: 401; authenticated status request: 200.
- `/readyz`: 503 while credentials are absent, as designed.
- Public BTC metadata and series discovery succeed; collector reports `waiting_for_credentials` with no error.
- Controlled restart completed, confirmed by shutdown/startup logs.
- Original experiment registration remained identical and present exactly once; stored observations and increasing event IDs survived. Evidence: `validation/railway-hosted.json`.
- Initial idle measurement: about 44 MB memory, maximum observed startup CPU about 0.021 vCPU, and about 85 MB used volume space. This is not a forecast of authenticated-feed or replay load.

## Cost cleanup

At the user's request, all nine older projects were audited. Older active deployment records were not consistently visible in the CLI's latest-deployment view, so the final audit checked every environment's `activeDeployments` directly. All old projects now have zero active deployments, scheduled runs, deployment triggers, attached volumes, and buckets. GitHub connections for cooperative-art and project_icarus, and the old Postgres image source, were disconnected.

The user explicitly approved deletion of five retained data volumes, about 3.64 GB total. All five are detached and pending permanent deletion on 2026-09-18, following Railway's 48-hour recovery period. Historical volume objects can remain visible in project metadata; active volume instances and pending-deletion flags distinguish them from attached storage. Do not claim the recovery-period storage has already been physically removed or that accrued charges have been reversed.

The existing workspace hard usage limit of **$10** was left unchanged. The Hobby subscription still applies. At the September 17 cleanup check, only this research service was running. See COMMISSIONING.md for subsequent authenticated-feed measurements.

## Remaining commissioning gates

1. Completed: user authorized the old Railway Kalshi key pair transfer; the key ID and base64 private key are installed. No key value was displayed or saved locally.
2. Completed: fresh BRTI/books, source/receipt timestamps and continuous rollover data verified.
3. Completed: two full markets, thresholds and official outcomes audited; 11 baseline fills independently reproduced and 57 fills checked across six execution scenarios.
4. Verify account-specific balance rounding and fee assumptions.
5. Archive restore, checkpoint continuity and a full day of compact-format cost measurement passed. Longer-term growth and full bare-volume recovery remain open.

## Authenticated feed check — 2026-09-17

The user explicitly requested credential reuse from old Railway variables. A read-only BRTI WebSocket subscription first verified the matching key ID/private key pair in `Kalyx_Final`. Only `KALSHI_API_KEY_ID` and `KALSHI_PRIVATE_KEY_B64` were copied into the new service, through stdin with command output captured. Old trading flags, endpoints, and strategy settings were not copied. Old services were not restarted.

Following redeployment, the collector reported `recording`, `/readyz` returned 200, and fresh benchmark and valid book data were present. Initial quality counts were zero malformed frames, zero clock regressions, and one expected new-session gap marker. Evidence: `validation/authenticated-feed.json`. This supersedes the earlier missing-credential readiness check above.

The first feed sample included 4,715 WebSocket events in approximately 23 seconds. That brief burst is not a long-term rate estimate, but it confirms that the two-million-event replay ceiling could become a near-term constraint. Capacity/checkpoint work remains tracked in issue #2; the existing limits have not been raised. Full-market outcome, fill, fee, and capacity auditing is still required before claiming sustained research commissioning.


### Rollover correction

The first live replay completed (13,680 events), but subsequent rollover snapshots omitted both depth arrays. The old normalizer incorrectly counted these as malformed and invalidated other books. Missing sides now clear that side of depth; explicitly malformed arrays still fail closed. Readiness additionally requires quotes on both sides. Seven new regression cases pass (34 total tests; Ruff clean).

The corrected source starts a separately registered experiment in `/data/normalizer-v2`. The original `/data/events.sqlite3` and its reports are retained, because changing normalization code must not silently change the original forward experiment. No feed or replay capacity limits were increased.

Deployment reached SUCCESS; external health and two-sided readiness returned 200 with fresh authenticated data and zero malformed frames. Reprocessing all 112,049 preserved original events with the corrected normalizer produced zero malformed frames. GitHub CI passed tests, image build and startup verification: https://github.com/kaiau00/kalshi-research-lab/actions/runs/35181515139. Sanitized hosted evidence: `validation/authenticated-feed-v2.json`.
