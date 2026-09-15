# Build plan

Confirmed by the user: fresh Desktop repository, private GitHub tracking, BTC first, Railway budget target up to $10/month, credentials supplied later.

## Checkpoints

1. Foundation: Python 3.12+, immutable experiment settings, tests/CI, documentation, private GitHub repository.
2. Capture: market discovery and metadata updates, authenticated book and BRTI streams, raw compressed append-only event storage, receipt/source timestamps, reconnection/gap markers, storage limits, health reporting. Public metadata collection works before credentials.
3. Replay: receive-order event replay; explicit book convention; sequence-gap invalidation; official threshold and results; BRTI final-minute conditioning; bounded volatility warmup; delayed IOC limit fills using available depth; fee rounding; reservations, cash and settled P&L. No live trading implementation.
4. Compare: basic fair value, tail-end underdog, fast/slow volatility fair value. Fixed $100 per strategy, $1 maximum order cost including fees, one filled entry per market, same hold-to-settlement policy. Save decisions, orders, fills, uncertainty, equity, and experiment manifest. Separate public historical candle screening from executable replay. Synthetic demo for verification only.
5. Host: one Railway service/volume with public minimal health route and password-protected dashboard, dedicated project, no credentials copied from old bots. Replay runs separately as a bounded subprocess against a frozen event prefix. Resume-safe forward paper state is derived by deterministic replay of that prefix; report receipt cutoff explicitly.

## Acceptance checks

- No order-placement endpoint or POST method in the Kalshi client.
- Future data, missing threshold, stale feeds, sequence gaps and unknown book conventions cannot produce fills.
- A 40-cent buy cannot fill a 55-cent ask. Both sides use correct complement prices. No automatic maker fills.
- Fees and reservations prevent overspending; cash reconciles through settlement; unsettled contracts remain open.
- Final-minute averaging conditions on observed values, counts each source second once and refuses gaps.
- Every run identifies its exact data prefix and config; reports never imply a synthetic or candle test is live/executable performance.
- Historical screening uses one observation per market per window and reports limitations.
- GitHub CI passes. Railway reaches SUCCESS; health/data-readiness are verified independently.

## Research protocol

Defaults are hypotheses, not tuned parameters. Use 60/20/20 chronological train/validation/holdout market splits. Entire contracts stay in one split; training outcomes must be known before subsequent testing. Feature warmup may use earlier observations, never future outcomes. Do not optimize on holdout. An inspected holdout becomes development data if settings change.

Compare net P&L, drawdown, unresolved exposure, distinct contracts, daily results, entry calibration and fill/rejection rates. Small or correlated samples do not establish an edge. Bootstrap complete UTC-day blocks rather than individual ticks; show unavailable uncertainty when there are too few days. Initially no automatic optimizer, Kelly sizing, leverage, compounding, news trading, or live money.

## Deferred until genuine data exists

Authenticated integration needs the user's key. Reliable maker queue fills require richer empirical validation; v1 uses delayed liquidity-taking execution and refuses maker mode. Reversal/order-flow, multiple assets, full market making, and live orders are later milestones. A profitable strategy is not an acceptance promise.
