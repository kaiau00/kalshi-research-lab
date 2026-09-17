# Hosted research lab

Verified 2026-09-17. The research service is hosted and recording public BTC metadata. Authenticated order-book and BRTI subscriptions are now connected using the old Railway key pair at the user’s explicit request. Full-market execution and settlement commissioning is still pending. There is no live-order capability.

- Dashboard: https://research-lab-production-ade8.up.railway.app
- Railway service: https://railway.com/project/c6476eeb-df32-47aa-b0ef-262a50f8e9a8/service/a1bf43d4-6a8b-463a-9711-63a61e399688?environmentId=15e2863f-f700-45c7-973c-d00903bed9af
- Environment: production
- Deployed source commit: `c03b4c4` (later documentation-only commits need no app redeploy)
- Active deployment: `80a999e9-d74f-42a3-916f-25930d8b0db3`, observed `SUCCESS`
- One replica; persistent volume `research-lab-volume` mounted at `/data`
- HTTPS domain target port: **8080**, matching the Railway-assigned `PORT`

## Access and credentials

Dashboard username: `lab`. A generated password is saved locally in the ignored `.env.dashboard` file in the Desktop repository; it is not committed or included in Docker uploads. The same value is configured as `LAB_DASHBOARD_PASSWORD` on Railway.

The authorized key ID and base64 private key are configured as Railway secret variables. Do not commit either credential. Full-market execution and settlement auditing remains open.

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

The existing workspace hard usage limit of **$10** was left unchanged. The Hobby subscription still applies. Only this research service is running; longer-term resource cost and data throughput still need validation once authenticated feeds are enabled.

## Remaining commissioning gates

1. Completed: user authorized the old Railway Kalshi key pair transfer; the key ID and base64 private key are installed. No key value was displayed or saved locally.
2. Confirm fresh BRTI and book snapshots, sequence recovery and both receipt/source timestamps.
3. Audit at least two complete BTC markets, official thresholds, outcomes and simulated fills.
4. Verify account-specific balance rounding and fee assumptions.
5. Measure real feed/replay usage against the budget and test archival capacity before a multi-week experiment.

## Authenticated feed check — 2026-09-17

The user explicitly requested credential reuse from old Railway variables. A read-only BRTI WebSocket subscription first verified the matching key ID/private key pair in `Kalyx_Final`. Only `KALSHI_API_KEY_ID` and `KALSHI_PRIVATE_KEY_B64` were copied into the new service, through stdin with command output captured. Old trading flags, endpoints, and strategy settings were not copied. Old services were not restarted.

Following redeployment, the collector reported `recording`, `/readyz` returned 200, and fresh benchmark and valid book data were present. Initial quality counts were zero malformed frames, zero clock regressions, and one expected new-session gap marker. Evidence: `validation/authenticated-feed.json`. This supersedes the earlier missing-credential readiness check above.

The first feed sample included 4,715 WebSocket events in approximately 23 seconds. That brief burst is not a long-term rate estimate, but it confirms that the two-million-event replay ceiling could become a near-term constraint. Capacity/checkpoint work remains tracked in issue #2; the existing limits have not been raised. Full-market outcome, fill, fee, and capacity auditing is still required before claiming sustained research commissioning.


### Rollover correction

The first live replay completed (13,680 events), but subsequent rollover snapshots omitted both depth arrays. The old normalizer incorrectly counted these as malformed and invalidated other books. Missing sides now clear that side of depth; explicitly malformed arrays still fail closed. Readiness additionally requires quotes on both sides. Seven new regression cases pass (34 total tests; Ruff clean).

The corrected source starts a separately registered experiment in `/data/normalizer-v2`. The original `/data/events.sqlite3` and its reports are retained, because changing normalization code must not silently change the original forward experiment. No feed or replay capacity limits were increased.
