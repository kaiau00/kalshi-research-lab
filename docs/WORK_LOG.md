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

Railway deployment `d0771b3b-a2e4-4384-bb83-3962ac97dc53` reached SUCCESS from source `4792d34`. Protected status reported `watching` and the exact adaptive parameters. Its first entry bought three NO contracts at $0.89 with $0.0206 fees, modeled 98.06% NO probability and 8.37 percentage points of net edge at 299.31 seconds remaining. The official NO settlement produced +$0.309400. Hosted ledger inspection reconciled the fill cost, fee, quantity and result exactly.

At the 17:44 UTC follow-up, the adaptive ledger had four exchange fills and four official settlements, +$9.001400 realized P&L, $165.8550 exchange-2 cash and no unresolved orders. A transient demo API `HTTPStatusError` put the loop into `waiting_api`; the built-in retry loop cleared the error and returned to `watching` without manual intervention. Four demo trades are too few to establish an edge, especially given the earlier negative historical comparison.

## September 30 UTC — v6 three-strategy comparison

Froze the cumulative prospective v6 replay at 425,326,032 receipt-ordered events through archived segment 4,344. The exact report, checkpoint, archive-prefix rows and checksum manifest are preserved under `/data/comparisons/v6-002`; collection continues independently. All three accounts used the same registered $100 bankroll, $1 risk cap, 4% minimum edge and 500 ms delayed-IOC simulator.

Basic fair value lost $61.4350 across 564 settlements, tail underdog lost $3.2847 across 238, and adaptive volatility gained $5.6672 across 616. Adaptive had the best full-prefix P&L, drawdown and calibration, but becomes -$15.3936 without its largest winner, was positive on only four of ten UTC dates, and remains too short for the preregistered daily bootstrap. No strategy is promoted. Full interpretation and the sanitized manifest are in STRATEGY_COMPARISON_002.md and validation/comparison-002-summary.json.

Declared Candidate Study 003 before starting post-cutoff processing. Four signal-only accounts will compare unchanged adaptive volatility, a fixed market-prior blend, a development-fitted symmetric calibration transform, and the calibrated model with fixed spread, slippage, depth and quote-persistence guards. The study begins after v6 segment 4,344 and requires at least 20 forward UTC dates plus 100 settlements before review. See CANDIDATE_STUDY_003_PROTOCOL.md.

## October 1 UTC — Candidate Study 003 commissioned

Implemented the four preregistered candidates as isolated signal-only accounts. They share the existing receipt-order state, fee and delayed-IOC execution model but have fresh independent $100 balances and no exchange submission path. The fitted symmetric calibration coefficient is frozen at `0.7459916645763038`; its development log loss changed from `0.5148963080793826` to `0.5039266910399527`. The guarded candidate enforces the declared six-cent spread, two-cent adverse-price, two-times-depth and consecutive-second quote checks.

Source `569f4a9` passed 110 local tests, Ruff and GitHub run `36797348997`. Deployment `df33997d-324c-47d5-9eb5-c5ebfb88284a` reached SUCCESS in the existing single Railway service. The durable registration exactly matches the installed candidate source, and the checkpoint checksum, registration hash, dataset, seed segment 4,344, seed digest and all four account names were independently read back from `/data/candidate-studies/003`. At commissioning it was actively catching up from segment 4,345 while the main v6 recorder remained connected and ready.

The deployment exposed one older adaptive-demo POST with a read timeout. The complete ticker-specific order page had no matching client ID and no cursor; the ticker had no settlement or position, and exchange-2 cash was exactly `$156.8536 + $15.2215 = $172.0751`. That evidence was saved under a durable `manual_reconciliation:` metadata key, the intent was marked definitively rejected without retry, and the adaptive runner returned to `watching` with 41 settlements, +$15.2215 and zero unresolved orders.

The current billing period showed $4.3246 used, a $7.5731 estimate and the unchanged $10 hard cap. During backlog replay, CPU was 1.13 vCPU current / 1.31 maximum against an 8-vCPU limit and memory was 284 MB current / 363 MB maximum. These are brief commissioning measurements; cost and latency must be checked again after catch-up.

Declared development-only Parameter Study 004 before its worker or registration consumed archived events. It fixes 40 configurations across probability model, net-edge threshold, entry window, spread and quote persistence, with five chronological blocks, concentration/calibration/drawdown gates and one- and two-cent cost stresses. The input is the already viewed v6 prefix through segment 4,344; any selection requires a new prospective study and cannot change Candidate Study 003. See PARAMETER_STUDY_004_PROTOCOL.md.

## October 1 UTC — Parameter Study 004 commissioned

Implemented the bounded Study 004 worker after the protocol commit. It replays the frozen v6 segment 0–4,344 development prefix through the same receipt-ordered delayed-IOC simulator and evaluates all 40 fixed configurations from one shared market state. It checkpoints every 25 segments, stops at the declared terminal segment, and records actual P&L, top-three-winner concentration, one- and two-cent cost stress, daily and five-block results, calibration, fixed volatility regimes, drawdown, and every promotion gate. It cannot submit an exchange order. Candidate Study 003 remains separately registered and unchanged, and the original `adaptive_volatility` demo trader remains the only active order-submission strategy.

Source `264da32` passed 117 local tests, Ruff, and GitHub run `36800595765`. Deployment `c55cce15-7021-4e3a-8420-3e3bd94030c7` reached SUCCESS in the existing single Railway service. The first hosted checkpoint at segment 25 independently matched the declared dataset, source hash, registration hash, checkpoint checksum and terminal event digest, and contained all 40 accounts. At the later commissioning check, the worker had processed 75 of 4,345 segments with no error. Those early results cover only one UTC day and are intentionally not interpreted; no configuration can be promoted directly from this development search.

The v6 recorder remained connected and ready while the study ran, with 473,217,746 archived events through segment 4,829 at the snapshot. Candidate Study 003 had caught up and was waiting for segment 4,830. The adaptive demo runner reported `watching`, 43 attempts, 42 fills, 41 official settlements, +$15.221500 realized P&L, no unresolved order and one filled market awaiting settlement. The current bill was $4.3479, Railway's estimate was $7.5996, and the unchanged workspace hard limit was $10. The volume used about 3.21 GB of 5 GB; post-catch-up memory was about 216 MB.

## October 2 UTC — Study 004 result and demo recorder recovery

Study 004 completed all 4,345 declared segments and 425,326,032 receipt-ordered events across ten UTC dates. Seven of 40 configurations had positive headline P&L, but none remained profitable after removing its three largest winners, only one survived two-cent execution stress, none was positive in four of five chronological blocks or on a majority of days, and no configuration passed all gates. The best headline result, `window_blend25_e06_30_180`, made $19.3280 but fell to -$32.3316 without its top three winners and had a $43.68 drawdown. Its two largest winners bought 2.1- and 3.5-cent contracts and contributed $44.5945. The complete sanitized metrics and trade examples are in PARAMETER_STUDY_004_RESULTS.md and validation/parameter-study-004-summary.json. No Study 005 candidate was selected.

The adaptive demo runner later stopped safely when its original single-file audit log reached the 256 MB guard. One IOC POST for `KXBTC15M-26OCT011245-45` had timed out and remained uncertain. After finalization, complete order and fill pages had no matching client ID and no cursor, the settlement page and position set were empty, no resting order existed, portfolio value was zero, and $179.6610 exchange-2 cash exactly equaled $156.8536 starting cash plus $22.8074 from 60 recorded settlements. This evidence was committed under the intent's `manual_reconciliation:` metadata key with SHA-256 `be11877b27e36e582affc7dfc7a6e056f2ca79fc0fdaf561c3eb18d1f5aedf7`; the intent was marked rejected without retry, leaving zero pending orders.

Source `34ecd71` replaces the finite demo event file with a separately registered receipt-ordered segmented recorder. It preserves the 251,858,944-byte legacy SQLite file unchanged, links segments by digest, uploads compressed segments under a demo-specific bucket prefix, verifies every uploaded byte by reading it back, and removes a hot segment only after the catalog commits the verified checksum. Upload failure leaves the sealed segment local and retries; a separate 750 MB hot reserve remains fail-closed if archival stays unavailable. All 119 tests, Ruff and GitHub run `37034543611` passed. Deployment `22609b9c-3e49-4e57-a4a7-ec4dba5d069e` reached SUCCESS with one running instance. The original adaptive settings and Candidate Study 003 registration remained unchanged. Protected status returned `watching`, 60 fills and settlements, +$22.807400, $179.6610 cash, zero unresolved orders and a healthy new recording dataset `8bfb615900d646b9912ae32b79cc847b`.

The first hosted segment contained 446 events and terminal digest `80ff00b0bd2956e1c6651f1a7471ce56a1679ddaae6e62d168d587b3a538b898`. An independent full bucket download matched archive SHA-256 `b705d5c78d55a5cabe82ca7497db11b84db41d06432838a26c736b29305bea2f`, reconstructed all 446 event hashes, found the exact dataset registration first, and confirmed the hot SQLite copy had been removed only after the catalog reached `archived`.

Railway then reported $5.5064 current usage and an $11.6001 period estimate against the unchanged $10 hard cap. The estimate includes the completed 425-million-event replay. Disabled only the completed Study 004 worker so the service no longer loads its large checkpoint; its result and durable files remain intact. Deployment `c3fc6d2f-500d-406c-8cd0-34c8af91dc86` reached SUCCESS. Current memory fell from about 409 MB to 202 MB, while v6 recording, Candidate Study 003 and adaptive demo execution remained healthy. The estimate may lag the reduced memory load; no limit was raised.

## October 3 UTC — demo versus production audit

Matched all 114 settled adaptive demo fills against the existing verified production adaptive checkpoints, avoiding a second download and replay of 189 million events. Only 14 demo trades had a same-side production fill within two seconds. Those trades contributed +$4.4283 in demo P&L and +$3.4251 in the separately sized $1-cap production replay. The other demo trades contributed +$28.2876, and none of the five largest demo wins had a close same-side production fill. All comparable inferred thresholds matched exactly. Ten trades had an opposite-side production decision within two seconds and contributed +$19.5350 of demo P&L. The result indicates that demo-book prices or availability, rather than different contract terms, explain most of the unusually strong demo return.

Source `9bb746f` adds the repeatable checkpoint comparison and direct production snapshots for every future demo order. Signal and 500 ms snapshots record the production threshold, both asks, displayed depth, quote age, adaptive forecast, fees, edge and qualification without delaying the demo POST or adding a production-order path. All 123 tests and Ruff passed. Deployment `0cc46d37-aeef-4510-bf9f-f34fbb6b8d5c` reached SUCCESS; health/readiness were 200, the adaptive runner returned to `watching` with 114 settlements, +$32.7159 and zero unresolved orders, and Candidate Study 003 remained active and unchanged.
