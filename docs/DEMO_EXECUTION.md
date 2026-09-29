# Kalshi demo strategy experiments

**September 27, 2026 status:** tail-underdog experiment 001 is deployed successfully on Railway as `e1c08e9e-2a76-4207-8a46-2393c02b170f`, source `6345828`. The runner is connected to BRTI, discovering BTC `KXBTC15M` Predictions markets, and reports `watching` with a $3 maximum modeled cost per market. Its new ledger started at the verified $157.5630 exchange-2 balance and had zero attempts, fills, settlements, unresolved orders, or P&L at commissioning. `/demo` is available with the existing dashboard credentials.

The completed fair-value ledger is frozen under `/data/demo-fair-value-001`: 133 attempts, 132 exchange fills, 132 official settlements, no unresolved orders, and +$32.563000 realized P&L. Its raw audit recorder reached the declared 256 MB cap and stopped before the strategy switch. That result remains a small, demo-liquidity sample and does not establish a profitable real-market edge.

The user authorized trading the existing Kalshi demo account with a $125 practice bankroll on September 23, 2026, authorized retrieving its matching credentials from old Railway variables, raised the per-market cap to $3 on September 24, and requested the tail-underdog strategy on September 27. The exact key pair was found in kalyx-perp and authenticated successfully to the demo balance and BRTI endpoints. No production order submission is authorized or implemented.

The recovered account initially reported $125.54, all on exchange 0, with no positions or resting orders on exchange 2. BTC 15-minute demo markets are on exchange 2. Exactly $125 of practice funds is now allocated there, leaving $0.54 on exchange 0. These are internal exchange indexes within the Predictions `event_contract` account; Perpetuals and the `margined` account are outside this experiment. The execution service does not contain automatic fund-transfer logic.

## Strategy and execution

The active strategy is `tail_underdog` on BTC `KXBTC15M`. It evaluates only 5–135 seconds before close, requires the forecast to be within one standard deviation of the threshold, selects only the cheaper outcome, requires its ask to be at most $0.35, and requires at least four percentage points of modeled net edge after fees. These are the existing declared research parameters; they were not tuned against the completed fair-value trades. The maximum modeled cost is $3 per market. The strategy can use actual available cash up to its fixed $157.5630 starting baseline, so profits are not compounded into larger sizing.

The existing research probability and decision functions are reused. The runner allows up to three attempts ten seconds apart and no reentry after any fill. Position sizing reserves a cent-rounded cost per contract conservatively. The three research accounts retain their existing $100 registrations and histories. A durable strategy registration prevents a ledger from being silently reused for a different strategy.

## Prospective frequency study

On September 28, the runner began an append-only, signal-only comparison of `tail_control_135s` and `tail_window_180s`. Both use the same $0.35 maximum price, absolute z-score limit of 1.0, 4% minimum modeled net edge, inputs and timestamps; only `tail_max_seconds` differs. Each variant records at most its first qualifying signal per market in the durable order ledger. Shadow signals never create exchange orders, reserve funds, change the live account, or affect the live strategy's attempt/fill guards. The active exchange strategy remains the 135-second control with the $3 cap.

Quotes from 135–180 seconds are fetched only for the shadow comparison. Rejected extended-window quotes are not added to the private demo audit log; any qualifying shadow signal stores its decision and forecast. Complete continuous benchmark and order-book price action remains available in the separately segmented v6 research archive for reproducible historical replay.

Demo BRTI streams continuously. Demo REST quotes are sampled approximately once per second in the entry window, with quote age conservatively measured from request start. Demo metadata, thresholds, fees and order books are used throughout; there is no production quote substitution. Missing, stale or one-sided quotes block entries. Actual demo orders use IOC limits, integer requested contracts, and the current V2 YES-book convention: YES buys are bids; NO buys are asks at `1 - NO limit`.

Execution uses measured network latency rather than the research simulator's 500 ms delay. Partial fills, costs, fees and final account settlements are read from the demo exchange. Settlement quantities and costs must reconcile with tracked fills before P&L is attributed. Demo liquidity and performance are not evidence of production profitability.

## Recovery and scope

`demo_execution` has hardcoded demo REST/WebSocket hosts, separate demo credential names, no production-key fallback, no redirects, no withdrawal/transfer methods and no general-purpose write endpoint. Every order intent and unique client ID is committed with SQLite FULL synchronous mode before submission. No POST is automatically retried. Unknown requests block all new orders until the exact client ID is found and reconciled. They remain blocked across restarts. Responses that violate identity, quantity, IOC terminal status, or the configured $3 budget stop execution for inspection.

A process lock prevents concurrent runners against the same ledger. The existing research recorder runs alongside the optional demo task in the same Railway service. The source files under `research_lab` remain unchanged, preserving v6 registration/checkpoint compatibility. Demo starts record both source hashes. The active raw audit log and order/settlement ledger live under `/data/demo-tail-underdog-001`; the completed fair-value files remain untouched under `/data/demo-fair-value-001`.

`LAB_DEMO_ENABLED=1` enables the task. `LAB_DEMO_STRATEGY` selects an allowlisted research strategy, `LAB_DEMO_DIR` selects its isolated ledger, and `LAB_DEMO_STARTING_CASH` sets the exact first-order funding gate. `KALSHI_DEMO_KEY_ID` and `KALSHI_DEMO_PRIVATE_KEY_B64` remain separate Railway variables. `/demo` and `/api/demo/status` use the existing dashboard password. Creating `/data/demo-tail-underdog-001/STOP` stops new order attempts; removing it resumes evaluation. An uncertain order still requires reconciliation. No resting orders are deliberately created.

Before its first tail order attempt, the runner requires the exchange-2 cash balance to be exactly $157.5630. Otherwise its status is `waiting_initial_demo_funding`. It continues recording and reading balances while waiting, and cannot send an order. After the first attempt, subsequent orders use the actual remaining balance up to the fixed starting baseline.

Raw demo capture stops at 256 MB and preserves its data; it does not silently rotate or upload demo account data to the market-data archive. It is an account/execution audit, not the primary long-history backtest source. The v6 research dataset continuously records BRTI, book events, market metadata and official outcomes in receipt order, seals bounded segments, verifies compressed archives, and maintains a replay checkpoint. The volume ledger survives ordinary service restarts, but bare-volume disaster recovery is not automated. The additional demo workload has not yet received a full-day cost measurement. No new Railway service, old-bot restart, or workspace limit increase is required.

Local validation for the strategy switch: 99 tests and Ruff passed. External health/readiness returned 200; the protected demo status returned 200 and reported an active tail runner with the exact declared parameters and zero initial attempts. A direct preflight and post-deploy read found no positions or resting orders. The research recorder retained dataset `e2d5cb33e7c44660809b531f03d4b4e3`.

## Primary API references

- [Demo environment](https://docs.kalshi.com/getting_started/demo_env)
- [API keys](https://docs.kalshi.com/getting_started/api_keys)
- [Exchange sharding](https://docs.kalshi.com/getting_started/exchange_sharding)
- [Intra-account transfers](https://docs.kalshi.com/api-reference/portfolio/intra-account-transfer)
- [V2 orders](https://docs.kalshi.com/api-reference/orders/create-order-v2)
- [Order direction](https://docs.kalshi.com/getting_started/order_direction)
- [Account settlements](https://docs.kalshi.com/api-reference/portfolio/get-settlements)
