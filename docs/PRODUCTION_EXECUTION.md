# Production execution 001

This document preserves the completed adaptive-volatility production revision. It is no longer accepting new
entries. The current authorized runner is documented in
[Market Anchor live pilot 001](MARKET_ANCHOR_LIVE_PILOT_001.md) and uses a separate ledger with a $1 all-in
maximum per market.

The production adapter implements the user-authorized October 7, 2026 real-money pilot. It is deliberately
separate from `demo_execution` and uses a new durable ledger at
`/data/production-adaptive-001/orders.sqlite3`.

## Frozen scope

- Series: `KXBTC15M` only
- Exchange index: 2 (Crypto & Commodities)
- Subaccount: 0
- Strategy: `adaptive_volatility`
- Bankroll baseline: $100; profits do not increase sizing
- Maximum all-in entry cost: $2 per market for future entries under `adaptive-fixed-risk-002-20261008`
- Sizing: fixed; no Kelly sizing
- Entry window: 5 to 300 seconds before close
- Minimum modeled net edge: 0.04 after the configured taker fee
- Variance: 70% of the last 60 seconds plus 30% of the last 600 seconds
- Entry execution: 500 ms delayed IOC, at most three signal attempts and one entry fill per ticker
- Position policy: hold every future fill to Kalshi's official settlement
- Position monitoring: verify the signed exchange position against the durable ledger once per second
- Early-exit submission: disabled under `adaptive-hold-settlement-002-20261008`

## Required deployment guards

Production execution starts only when `LAB_PRODUCTION_ENABLED=1`,
`LAB_PRODUCTION_AUTHORIZATION=real-btc-15m-adaptive-3usd-2026-10-07`, and
`LAB_PRODUCTION_RISK_AUTHORIZATION=real-btc-15m-adaptive-2usd-2026-10-08`. The original authorization and
registration are retained as immutable history; the risk authorization lowers all future entry orders to a $2
all-in maximum. Hold-only execution additionally requires
`LAB_PRODUCTION_HOLD_AUTHORIZATION=real-btc-15m-adaptive-hold-settlement-2026-10-08`. The application refuses to
run demo and production execution simultaneously. The account must initially expose exactly $100 on exchange
index 2 and no positions or resting orders.

Before every submission, the runner verifies exchange and shard status, account cash, the absence of any nonzero
shard-2 position or resting order, a fresh production order book, and that the original limit remains marketable
at the modeled arrival time. Every signal is written before its 500 ms delay, so arrival cancellations count
toward the same three-attempt limit as replay. It writes entry intents with SQLite `synchronous=FULL` before each
POST. There are no automatic POST retries. An unknown request result blocks later orders until the exact client
order ID is found.

The monitor verifies that the signed exchange position exactly matches the durable ledger and then waits for the
official result. It has no early-exit order path. Any foreign or mismatched exposure stops new execution.

`/data/production-adaptive-001/PAUSE_ENTRIES` pauses only new entry evaluation. Settlement reconciliation,
uncertain-order reconciliation, position verification, and historical exit auditing continue while that file is
present. The broader `STOP` file remains an emergency process-loop stop and should not be used for a routine entry
pause when a position may still require verification or settlement bookkeeping.

## Exit-versus-hold audit

Every filled monitored exit remains linked to its original entry. After Kalshi publishes the official binary
result, the runner writes one immutable counterfactual record with:

- actual net P&L from the exit, including entry and exit fees, plus any officially settled remainder;
- net P&L that the original full entry would have earned if held to the official result; and
- exit advantage, defined as actual net P&L minus hold-to-settlement net P&L.

A positive exit advantage means the exit saved money relative to holding; a negative value means the exit cost
money. The protected production status reports resolved and pending comparisons, aggregate actual and hold P&L,
helped/hurt counts, and the ten most recent market-level records. This audit is retained for the completed
`adaptive-monitored-exit-001-20261007` phase and submits no orders. New fills use the hold-only policy above.

Kalshi settlement records may report gross YES and NO quantities after a reduce-only offset. Historical partial
exits are reconciled by verifying the signed net quantity (`YES - NO`) against the durable remaining position;
future hold-only positions normally settle with only the originally purchased side.

The production client contains no transfer or withdrawal method. Funding is a separate one-time commissioning
operation. Production status is password protected at `/api/production/status` and `/production`.

## Evidence limits

The real-money pilot was authorized before the preregistered promotion studies completed. The prior exact-arrival
production audit was negative: only 41 of 152 settled demo fills qualified against production quotes, and those
41 lost $2.1620 before adverse-price stress. Demo profits therefore must not be treated as expected live returns.
Candidate Study 003 and Risk Sizing Audit 001 continue without parameter changes.
