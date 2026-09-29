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


## September 18–20 — execution audit and fee guards

Audited 2,397,032 archived v3 events using an independent raw-book reconstruction and independent rounding arithmetic. All 11 baseline fills exactly matched the preserved forward ledger; 57 fills across six execution scenarios passed price/depth/latency/fee/reservation checks, with all cash ledgers reconciled. All three defaults lost in this tiny five-market sample; results are diagnostic, not a parameter ranking or holdout claim.

Verified the official fee coefficient and rounding documentation. Added timestamped event fee metadata, precedence for overrides, stale/missing-fee rejection and inactive-market rejection. Deployed v5 separately, preserving earlier raw data. Work was interrupted by a Codex usage-limit rejection after deployment started; subsequent September 20 checks observed deployment SUCCESS, healthy feeds, over 95 million events, 981 archives and zero backlog. Active fee metadata and checkpoint identities/accounting passed.

GitHub CI exposed initial polling that incorrectly depended on host monotonic uptime. Corrected both series and event first-request handling, added zero/short-uptime regressions, and verified 58 local tests, Ruff and GitHub's production-container job. Source 7742abc. This operational fix uses a fresh v6 registration, preserving v5's two-day sample and original simulated accounts.

A complete day of compact-format measurements implies about $8.60/month at a repeated workload, including a $1 archive allowance. This is a planning estimate, not a billing guarantee; increasing account/checkpoint history remains a cost risk. No workspace spending limit was changed. Full bare-volume recovery and strategy selection/untouched validation remain outstanding.

The v6 deployment reached SUCCESS (7bbc756b-11f6-4e16-825f-b8e4ba6eaa7b). Health/readiness returned 200, unauthenticated dashboard 401, and both streams connected. Series metadata was recorded about 0.15 seconds after registration and event metadata within 6.1 seconds; prior v5 checkpoint remains present. All earlier recordings remain intact.

The first v6 compact archive (100,000 events) passed full download checksum, reconstructed terminal hash and registration checks. Its replay checkpoint checksum/source matched and advanced to segment 1.


## September 21 — first registered strategy comparison

Committed the comparison protocol before inspecting v5 strategy P&L, then froze 95,466,332 events / 982 segments with matching checkpoint, catalog, registration and account identities. Froze 140 development, 47 validation and 47 held-out closed markets. Opened only development/validation. The analysis attributes the original continuous forward paper ledger; it does not reset bankrolls or claim a new full raw replay. No production source/config or deployment changed.

Basic fair value: +$16.3289 development / +$5.8028 validation. Tail: -$6.1423 / -$3.1652. Adaptive: -$0.2469 / -$8.1105. Basic's validation becomes -$8.2698 without a single $14.0726 winner. Independently checked that winner's limit, observed fill depth/price, latency and recorded official result across 12 original archive segments; all checks passed. This is concentration-sensitive paper performance, not evidence of a reliable executable edge.

All 61 tests and Ruff pass. Report STRATEGY_COMPARISON_001.md records exact settings, trades, drawdown, fees, calibration, limitations and provenance. No parameters were tuned, no strategy promoted, and the held-out performance remains undisclosed. Too few observed days for the predeclared uncertainty/selection gate; continue prospective data collection and require a separate declared development study before tuning.

## September 23–24 — demo account integration

The user requested fair-value trading with $125 of Kalshi demo funds and retrieval of the key from old Railway projects. Found the exact matching ID/private key in kalyx-perp; verified demo balance $125.54, authenticated demo BRTI, and no active exposure/resting orders on crypto exchange 2. BTC demo markets are available but their books can be one-sided. No old service was restarted and no credentials were printed or committed.

Added an isolated demo-only execution package using the existing fair-value decision model. Durable intent/reconciliation logic, strict demo hosts and scoped IOC order bodies, conservative sizing, restart/uncertain-order guards, exchange-reported settlement attribution, and protected demo status are covered by tests. Research source files and v6 account registration remain unchanged. See DEMO_EXECUTION.md for operating limits; deployment and actual exchange execution require separate verification below.

September 24: pushed e2b7b41; GitHub checks including container startup passed (run 36011519495). The one $125 mock-funds transfer request returned HTTP 504; a read-back showed unchanged balances and no matching new transfer in the most recent history page. The request was not resubmitted. Added a first-order funding gate requiring exactly $125 on exchange 2; 92 tests and Ruff pass. Copied and verified the demo key pair and enabled configuration in the existing Railway service without printing secrets or triggering an intermediate deployment. The transfer is still unconfirmed at this stage.

Deployed df3f4cf successfully as 62072295-2308-4b85-970b-aae1c4016ca7. GitHub run 36012077117 passed. At the external post-deploy check, health/readiness and authenticated demo status returned 200. Demo BRTI was fresh, the runner was active, current BTC markets were discovered, and the funding gate correctly reported cash $0 with zero submitted attempts. Research continued on the unchanged v6 dataset with 1,804 archived segments, both feeds connected and no recorder error. No actual demo order or settlement has yet been exchange-verified; funding remains the blocker.

Later September 24: reconciled the uncertain HTTP 504 funding request against balances, transfer history, positions and resting orders. It had produced no transfer record or balance change. A single retry through Kalshi's supported alternate demo API host returned transfer ID `6c122eeb-bdb4-4565-b778-18d952798dc4`; read-back verified $125.0000 on Predictions `event_contract` exchange index 2 and $0.5400 on index 0. Perpetuals/`margined` funds were not used. The live runner advanced to `watching` with fresh status, zero submitted attempts, zero fills, zero unresolved orders and no error. Actual order, fill and settlement behavior remains to be verified from the first qualifying signal.

After 25 attempts, the exchange reported 24 fills and 24 settlements, with one zero-fill IOC, no unresolved orders, and +$0.3983 realized P&L. At the user's request, paused new entries and implemented an explicit risk revision from $1 to $3 maximum modeled cost per market. The revision preserves the existing order and settlement ledger, rejects any migration with a pending or unsettled fill, and keeps the BTC-only, Predictions-only, four-percentage-point edge and 5–300-second entry rules unchanged. Ruff and 95 tests passed. Source `f9bd9e2` deployed as `738d7ad4-3f14-481b-a514-29ce4130f83c` and reached SUCCESS. The hosted ledger recorded exactly one revision, retained all 25 intents and 24 settlements, and the runner resumed in `watching` state with risk `3.00`, cash $125.3983, no unresolved order, and no error.

## September 27 — isolated tail-underdog demo experiment

The fair-value raw audit log reached its declared 256 MB capacity and stopped safely. Direct account and ledger inspection found 133 attempts, 132 fills, 132 official settlements, no unresolved orders, no positions, no resting orders, $157.5630 exchange-2 cash, and +$32.563000 realized P&L. The entire `/data/demo-fair-value-001` experiment was left frozen for comparison.

Added allowlisted demo strategy selection, an exact configurable starting-cash gate, dynamic strategy parameters in protected status, and a durable ledger strategy registration that rejects in-place strategy changes. The active `tail_underdog` settings are the existing research defaults: 5–135 seconds remaining, cheaper outcome only, ask at most $0.35, absolute forecast z-score at most 1.0, and modeled net edge after fees at least 4 percentage points. The order cap remains $3 per market and sizing does not compound beyond the $157.5630 starting baseline. Research source files were unchanged. All 99 tests and Ruff passed.

Source `6345828` was pushed to the private GitHub repository and deployed as `e1c08e9e-2a76-4207-8a46-2393c02b170f`, which reached SUCCESS. Railway now uses `/data/demo-tail-underdog-001`. External health/readiness and protected status returned 200; the runner reported `watching`, fresh BRTI and market discovery, the exact declared parameters, zero attempts/fills/settlements, no unresolved orders, and no error. Hosted SQLite inspection confirmed the new tail registration and confirmed the prior fair-value counts and P&L were unchanged.

A later single balance read returned a stale-looking $122.7164 despite the new ledger having no attempts and the account having no position or resting order. New entries were paused immediately. Transfer history showed no new movement, target allocation was empty, and three consecutive fresh exchange-2 reads returned $157.5630 with advancing server timestamps. The temporary stop was then removed. Protected status again reported `watching`, cash $157.5630, zero attempts and no error.

## September 28 — first tail-underdog review

The first five filled markets were officially settled: two wins, three losses, $5.9912 actual cost risked, +$2.0688 realized P&L, 34.53% return on filled cost, and a $3.0954 maximum realized drawdown. Exchange-2 cash reconciled exactly at $159.6318, with no position or resting order. The result is only +1.31% of the fixed starting bankroll and is concentrated in one +$5.1543 winner; without that winner, the other four trades total -$3.0855. Three orders received very small partial fills, so this five-market sample is not evidence of a durable edge.

All five fills complied with the declared tail rules: 5–135 seconds remaining, selected price no higher than $0.35, absolute forecast z-score no higher than 1.0, modeled net edge at least 4 percentage points, and actual cost no higher than $3. A sixth IOC submission returned HTTP 503 and remained `uncertain`, correctly blocking further submissions without retry. After that market finalized, exact-client-ID checks found no order, fill, settlement, position, resting order, or balance effect. The ledger records this evidence under `manual_reconciliation:fv-16361481aba14d7caadcdbf50c62e225`; the intent was marked definitively rejected and the runner returned to `watching` with zero unresolved orders.

## September 28 — 180-second signal-only shadow

Predeclared and deployed a prospective frequency comparison between the unchanged 135-second live tail settings and one candidate that changes only the maximum entry time to 180 seconds. Both durable shadow definitions retain the $0.35 price cap, z-score limit of 1.0 and 4% minimum net edge. They record at most one qualifying signal per market and have no code path to order submission. Extended-window rejected quotes are not persisted in the private demo log, limiting storage growth; qualifying decisions are recorded. All 103 tests and Ruff passed.

During commissioning, Kalshi's primary demo market-list endpoint returned HTTP 500. The documented alternate demo host worked for read-only requests, while the timestamp-filter combination failed on both hosts. Added fixed demo-to-demo read failover only; POST order submission remains single-attempt on the original host. Replaced server timestamp filters with the documented `status=open` filter and a strict local 30-minute close-time bound. Deployment `cdab6a9e-3c99-4075-bf34-cbde85939129` reached SUCCESS at source `4792d34`; the runner returned to `watching` with the prior five settlements and +$2.0688 intact, no unresolved order, and both shadow counts initially zero.

The main v6 archive remained healthy throughout: connected benchmark and book streams, no recorder error, dataset `e2d5cb33e7c44660809b531f03d4b4e3`, 372,804,629 receipt-ordered events, 3,813 verified archived segments, and 11.83 GB of compressed archives at the commissioning snapshot. This is the primary source for historical parameter replay. The tail demo audit separately held 205,285 timestamped events and its durable exchange ledger; its 256 MB raw cap remains finite.

## September 29 — adaptive-volatility demo experiment

At the strategy switch, the tail ledger held 11 attempts, 10 exchange fills, 10 official settlements, no unresolved orders, and -$0.709400 realized P&L. Its signal-only study recorded five qualifying 135-second signals and six qualifying 180-second signals. A direct account preflight found $156.8536 exchange-2 cash, zero portfolio value, no positions and no resting orders. The fair-value and tail ledgers were frozen unchanged.

Activated the existing `adaptive_volatility` research default with a fresh `/data/demo-adaptive-volatility-001` ledger and exact $156.8536 first-order funding gate. It evaluates both outcomes from 5–300 seconds before close, requires at least 4% modeled net edge after fees, and blends return variance 70% from the latest 60 seconds with 30% from the latest 600 seconds. The $3 maximum modeled cost, IOC-only execution, no automatic POST retry, durable intent reconciliation and non-compounding sizing rules remain unchanged. The earlier registered comparison was negative for adaptive volatility, so this is a forward demo experiment rather than strategy promotion.

Railway deployment `d0771b3b-a2e4-4384-bb83-3962ac97dc53` reached SUCCESS from source `4792d34`. Protected status reported `watching`, the exact adaptive parameters, and no runner error. Its first entry bought three NO contracts at $0.89 with $0.0206 fees, modeled 98.06% NO probability and 8.37 percentage points of net edge at 299.31 seconds remaining. The official NO settlement produced +$0.309400. Hosted ledger inspection reconciled the fill cost, fee, quantity and result exactly; no order remains unresolved.
