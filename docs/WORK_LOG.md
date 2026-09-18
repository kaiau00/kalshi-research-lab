# Work log

## 2026-09-14 — scope and foundation

- User approved BTC-only, $10/month Railway target, private `kaiau00/kalshi-research-lab`.
- Created fresh Desktop repository. No old bot source, credentials, or data imported.
- Verified a public current KXBTC15M market: `floor_strike`, `greater_or_equal`, explicit BRTI-average rules, and subcent price ranges are present. Use metadata, not ticker parsing or a cached spot opening value.
- Documented checkpoint plan and acceptance tests before implementation.

## Implementation and validation

2026-09-14: Implemented the recorder, hash-chained compressed SQLite store with a single-writer lock, book normalization, benchmark-average forecast, three independent simulated accounts, delayed IOC execution, reports, historical screening, protected dashboard and deployment files.

Validation: 27 regression tests pass. They cover limit enforcement, partial fills, cash/fee reconciliation, official settlement, stale/gapped inputs, book complements, duplicate index observations, accumulated settlement averages, unknown fees and fee changes during order latency, raw integrity/tamper detection, WAL backup/restore, deterministic replay, sealed holdout, forward registration, dashboard guards and RSA signing. Test-client dependencies emit two deprecation warnings; tests pass.

Public integration: 12 real BTC markets downloaded with candle data and zero download errors. The historical screen reports 5 unavailable/invalid quote samples rather than fabricating prices. This is an integration sample, not evidence for or against a trading edge.

Running-service smoke check: public metadata discovery succeeds; password is required; health is 200; data readiness without a Kalshi key is 503. A process restart preserves the event hash chain and a single experiment registration. Evidence is in `docs/validation/local-smoke.json`. No Kalshi credentials were read or installed.

Container validation: GitHub Actions successfully built the Docker image and started it with external networking disabled. The image includes the dashboard, requires authentication, passes process health, and correctly fails data readiness without a feed. [Container validation run](https://github.com/kaiau00/kalshi-research-lab/actions/runs/34920769606). Hosted commissioning remains unverified.

Hosting blocked: Railway rejected creation of the fresh project with “Usage limit exceeded. Please increase or remove the hard limit to resume resource provisioning.” No workspace spending setting or old service was changed. The user has been asked whether to leave hosting pending or resolve the limit themselves.

Remaining gates: clear the Railway provisioning block; deploy the new dedicated service and volume; add the user's Kalshi key through secret variables; audit real authenticated book/BRTI streams, account fee rounding, resource consumption and restart/recovery. These gates must pass before calling collection commissioned. No live trading code exists.


## 2026-09-17 — hosted service and cost cleanup

After the user activated Hobby, deployed the dedicated research service and persistent volume. Corrected the public domain target port through the dedicated domain API after an environment patch did not persist. Observed deployment SUCCESS and verified external health, authentication, public metadata discovery, and controlled restart with unchanged experiment registration and retained events. Kalshi credentials remain absent; authenticated feed auditing remains open.

The user requested no other running/costing projects and explicitly approved deleting five old volumes. Removed old active deployments, disconnected sources that could auto-deploy, and verified all nine old projects have no active deployments, scheduled runs, or deployment triggers. The old volumes are detached and scheduled for permanent deletion on September 18. Preserved the existing $10 workspace hard usage limit. See `DEPLOYMENT.md` for the hosted URL, access instructions, evidence and remaining commissioning gates.


## 2026-09-17 — authorized Kalshi credential migration

At the user's explicit request, retrieved the existing Kalshi key pair from old Railway variables. Verified it through a read-only authenticated BRTI subscription, then copied only the key ID and base64 private key directly into the new Railway service. Secret values were neither displayed nor saved locally. The earlier blanket no-credential-reuse repository rule now records this explicit user authorization.

Redeployment reached SUCCESS. Hosted collector reports recording; readiness is 200 with fresh valid order-book and BRTI observations. Initial data had no malformed frames or clock adjustments, and one expected new-session marker. Authenticated data collection is active; full-market execution/settlement auditing and high-throughput capacity work remain open.


Live rollover revealed snapshots with omitted empty depth arrays. Corrected normalization and two-sided readiness, preserving rejection of malformed present arrays. Added seven regression cases; 34 tests pass and Ruff is clean. Deploy the corrected source with a new experiment directory `/data/normalizer-v2` on the existing volume, preserving the initial raw dataset and its registration.

Corrected deployment `912c251f-b12a-406f-9b80-fe3ff059b757` reached SUCCESS; health/readiness 200. Original dataset preserved (112,049 events), now reprocesses with zero malformed frames. GitHub CI passed including Docker validation. Evidence: `validation/authenticated-feed-v2.json`.

## 2026-09-17 — exhaustive data validation

Verified the hash chain of all 5,334,381 captured events and SQLite structure. Zero malformed frames or in-session sequence discontinuities. All captured thresholds and outcomes agree with current official records. Discovered the forecast's settlement window was one second late; the corrected close-exclusive window matches all 15 completed official settlement values exactly. Fixed forecast boundaries locally; 37 tests and Ruff pass. No deployment or experiment-registration rewrite occurred.

Collection had stopped at its storage limit around 06:05 EDT, and replay exceeded its event cap. Opening book capture is delayed 15–53 seconds; most fully spanned markets lack some benchmark seconds. Three determined results were not refreshed to finalization. Recorded findings and acceptance gates in DATA_VALIDATION.md. The system is not ready for strategy validation, and recording remains stopped pending rollover/capacity fixes.


## September 17–18 — bounded collection, rollover and recovery

Implemented segmented SQLite recording, receipt-order links, verified private-bucket uploads, atomic JSON replay checkpoints and bounded incremental jobs. Preserved all original data. Split benchmark/book streams, pre-subscribe upcoming books, maintain benchmark continuity during rollovers, and follow official outcomes through finalization. Corrected packaging so the production image includes the archive SDK.

Overnight capture exceeded 33.6 million events, with 340 verified archives, no pending segment backlog and about 31 MB hot data. Restored and hash-verified 1,197,032 real events. Two complete markets had 900/900 benchmark seconds, complete settlement windows, valid reconstructed books throughout, and exact matches to finalized official settlement values. Checkpoint event totals and accounting identity/reservation invariants passed. This does not validate fill realism or profitability.

A six-hour egress measurement projected a total around $11/month, above target. Removed redundant digest strings from the archive representation while preserving every event field and exact hash reconstruction. A 100,000-event real archive shrank 60.05%; new and old formats both reject tampering. All 44 tests and Ruff pass. Committed source 0a51567, deployed SUCCESS as acd0d537-de9a-4a5d-92e5-b923165c38f6, and registered a separate v4 dataset. The previous v3 dataset and archives remain untouched. Health/readiness 200, both feeds connected. Planning estimate now $7–9/month at similar traffic; actual long-run compact usage remains to be measured. $10 workspace hard limit unchanged. See COMMISSIONING.md for limits and evidence.
