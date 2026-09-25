# Fair-value Kalshi demo experiment 001

**September 24, 2026 status:** deployed successfully on Railway as `62072295-2308-4b85-970b-aae1c4016ca7`, source `df3f4cf`. The demo runner is connected to BRTI, discovering BTC `KXBTC15M` Predictions markets, and reports `watching`. A reconciled retry allocated exactly $125 from Predictions `event_contract` exchange index 0 to Predictions `event_contract` exchange index 2; transfer `6c122eeb-bdb4-4565-b778-18d952798dc4` was accepted and the balance read-back verified $125.0000 on index 2 and $0.5400 on index 0. The runner has zero order attempts, positions or unresolved orders so far. `/demo` is available with the existing dashboard credentials. Actual order submission, fills and settlement are not yet exchange-verified.

The user authorized trading the existing Kalshi demo account with a $125 practice bankroll on September 23, 2026, and authorized retrieving its matching credentials from old Railway variables. The exact key pair was found in kalyx-perp and authenticated successfully to the demo balance and BRTI endpoints. No production order submission is authorized or implemented.

The recovered account initially reported $125.54, all on exchange 0, with no positions or resting orders on exchange 2. BTC 15-minute demo markets are on exchange 2. Exactly $125 of practice funds is now allocated there, leaving $0.54 on exchange 0. These are internal exchange indexes within the Predictions `event_contract` account; Perpetuals and the `margined` account are outside this experiment. The execution service does not contain automatic fund-transfer logic.

## Strategy and execution

Only `basic_fair_value`, BTC `KXBTC15M`, 5–300 seconds before close, minimum four-percentage-point modeled edge after fees. The existing research probability and decision functions are reused. The initial $1 maximum modeled cost per market was explicitly raised to $3 on September 24 after 24 settled fills; the durable ledger and $125 starting bankroll remain continuous across revision `risk-cap-3-20260924`. The runner allows up to three attempts ten seconds apart and no reentry after any fill. Position sizing reserves a cent-rounded cost per contract conservatively. The three research accounts retain their existing $100 registrations and histories.

Demo BRTI streams continuously. Demo REST quotes are sampled approximately once per second in the entry window, with quote age conservatively measured from request start. Demo metadata, thresholds, fees and order books are used throughout; there is no production quote substitution. Missing, stale or one-sided quotes block entries. Actual demo orders use IOC limits, integer requested contracts, and the current V2 YES-book convention: YES buys are bids; NO buys are asks at `1 - NO limit`.

Execution uses measured network latency rather than the research simulator's 500 ms delay. Partial fills, costs, fees and final account settlements are read from the demo exchange. Settlement quantities and costs must reconcile with tracked fills before P&L is attributed. Before the $3 revision, 25 orders had been attempted, 24 filled and settled, and realized P&L was +$0.3983. This small sample does not establish an edge. Demo liquidity and performance are not evidence of production profitability. The current research fair-value run had lost $43.80 across 151 settled markets when reviewed; no parameters were optimized for this demo.

## Recovery and scope

`demo_execution` has hardcoded demo REST/WebSocket hosts, separate demo credential names, no production-key fallback, no redirects, no withdrawal/transfer methods and no general-purpose write endpoint. Every order intent and unique client ID is committed with SQLite FULL synchronous mode before submission. No POST is automatically retried. Unknown requests block all new orders until the exact client ID is found and reconciled. They remain blocked across restarts. Responses that violate identity, quantity, IOC terminal status, or the configured $3 budget stop execution for inspection.

A process lock prevents concurrent runners against the same ledger. The existing research recorder runs alongside the optional demo task in the same Railway service. The source files under `research_lab` remain unchanged, preserving v6 registration/checkpoint compatibility. Demo starts record both source hashes; its raw audit log and order/settlement ledger live separately under `/data/demo-fair-value-001`.

`LAB_DEMO_ENABLED=1` enables the task. `KALSHI_DEMO_KEY_ID` and `KALSHI_DEMO_PRIVATE_KEY_B64` are separate Railway variables. `/demo` and `/api/demo/status` use the existing dashboard password. Creating `/data/demo-fair-value-001/STOP` stops new order attempts; removing it resumes evaluation. An uncertain order still requires reconciliation. No resting orders are deliberately created.

Before its first order attempt, the runner requires the exchange-2 cash balance to be exactly $125. Otherwise its status is `waiting_initial_demo_funding`. It continues recording and reading balances while waiting, and cannot send an order. After the first attempt, subsequent orders use the actual remaining balance.

Raw demo capture stops at 256 MB and preserves its data; it does not silently rotate or upload demo account data to the market-data archive. The volume ledger survives ordinary service restarts, but bare-volume disaster recovery is not automated. The additional demo workload has not yet received a full-day cost measurement. No new Railway service, old-bot restart, or workspace limit increase is required.

Local validation: 92 tests and Ruff passed. GitHub run 36012077117 passed tests and the isolated container startup check. External health/readiness returned 200; the protected demo status returned 200 and reported an active runner. The research recorder retained dataset `e2d5cb33e7c44660809b531f03d4b4e3`, both feeds connected and no recorder error after deployment.

## Primary API references

- [Demo environment](https://docs.kalshi.com/getting_started/demo_env)
- [API keys](https://docs.kalshi.com/getting_started/api_keys)
- [Exchange sharding](https://docs.kalshi.com/getting_started/exchange_sharding)
- [Intra-account transfers](https://docs.kalshi.com/api-reference/portfolio/intra-account-transfer)
- [V2 orders](https://docs.kalshi.com/api-reference/orders/create-order-v2)
- [Order direction](https://docs.kalshi.com/getting_started/order_direction)
- [Account settlements](https://docs.kalshi.com/api-reference/portfolio/get-settlements)
