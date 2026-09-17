# Hosted research lab

Verified 2026-09-17. The research service is hosted and recording public BTC metadata. Authenticated order-book and BRTI commissioning is still pending the user-provided Kalshi key. There is no live-order capability.

- Dashboard: https://research-lab-production-ade8.up.railway.app
- Railway service: https://railway.com/project/c6476eeb-df32-47aa-b0ef-262a50f8e9a8/service/a1bf43d4-6a8b-463a-9711-63a61e399688?environmentId=15e2863f-f700-45c7-973c-d00903bed9af
- Environment: production
- Deployed source commit: `c03b4c4` (later documentation-only commits need no app redeploy)
- Active deployment: `b021652d-be70-420c-be23-c82e989eb921`, observed `SUCCESS`
- One replica; persistent volume `research-lab-volume` mounted at `/data`
- HTTPS domain target port: **8080**, matching the Railway-assigned `PORT`

## Access and credentials

Dashboard username: `lab`. A generated password is saved locally in the ignored `.env.dashboard` file in the Desktop repository; it is not committed or included in Docker uploads. The same value is configured as `LAB_DASHBOARD_PASSWORD` on Railway.

In the Railway service Variables tab, add `KALSHI_API_KEY_ID` and `KALSHI_PRIVATE_KEY_PEM` (full PEM value), or use the supported base64 alternative. Do not commit either credential. After deployment, audit actual BRTI and order-book subscriptions before calling data collection commissioned.

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

1. User installs Kalshi credentials in Railway Variables.
2. Confirm fresh BRTI and book snapshots, sequence recovery and both receipt/source timestamps.
3. Audit at least two complete BTC markets, official thresholds, outcomes and simulated fills.
4. Verify account-specific balance rounding and fee assumptions.
5. Measure real feed/replay usage against the budget and test archival capacity before a multi-week experiment.
