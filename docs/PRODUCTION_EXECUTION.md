# Production execution 001

The production adapter implements the user-authorized October 7, 2026 real-money pilot. It is deliberately
separate from `demo_execution` and uses a new durable ledger at
`/data/production-adaptive-001/orders.sqlite3`.

## Frozen scope

- Series: `KXBTC15M` only
- Exchange index: 2 (Crypto & Commodities)
- Subaccount: 0
- Strategy: `adaptive_volatility`
- Bankroll baseline: $100; profits do not increase sizing
- Maximum all-in entry cost: $3 per market
- Sizing: fixed; no Kelly sizing
- Entry window: 5 to 300 seconds before close
- Minimum modeled net edge: 0.04 after the configured taker fee
- Variance: 70% of the last 60 seconds plus 30% of the last 600 seconds
- Entry execution: 500 ms delayed IOC, at most three signal attempts and one entry fill per ticker
- Position monitoring: once per second from the live production order book and updated BRTI forecast
- Exit execution: reduce-only IOC against displayed best-bid depth, at most three exit attempts per ticker
- Take profit: estimated net exit profit of at least $0.05 per contract after the modeled exit fee
- Value exit: net executable value exceeds the updated modeled settlement value by at least $0.02 per contract
- Thesis exit: updated modeled probability is at or below the entry all-in basis per contract
- Otherwise: hold to official settlement

## Required deployment guards

Production execution starts only when `LAB_PRODUCTION_ENABLED=1` and
`LAB_PRODUCTION_AUTHORIZATION=real-btc-15m-adaptive-3usd-2026-10-07`. Monitored exits additionally require
`LAB_PRODUCTION_EXIT_AUTHORIZATION=real-btc-15m-adaptive-monitored-exit-2026-10-07`. The application refuses to
run demo and production execution simultaneously. The account must initially expose exactly $100 on exchange
index 2 and no positions or resting orders.

Before every submission, the runner verifies exchange and shard status, account cash, the absence of any nonzero
shard-2 position or resting order, a fresh production order book, and that the original limit remains marketable
at the modeled arrival time. Every signal is written before its 500 ms delay, so arrival cancellations count
toward the same three-attempt limit as replay. It writes entry and exit intents with SQLite `synchronous=FULL`
before each POST. Exit orders set `reduce_only=true`, so Kalshi caps them at the current position. There are no
automatic POST retries. An unknown request result blocks later orders until the exact client order ID is found.

The monitor verifies that the signed exchange position exactly matches the durable ledger before evaluating an
exit. It uses the displayed best bid and available depth, never a midpoint or last trade. A partial IOC fill is
recorded and only the remaining verified position may be offered later. Any foreign or mismatched exposure stops
new execution.

## Exit-versus-hold audit

Every filled monitored exit remains linked to its original entry. After Kalshi publishes the official binary
result, the runner writes one immutable counterfactual record with:

- actual net P&L from the exit, including entry and exit fees, plus any officially settled remainder;
- net P&L that the original full entry would have earned if held to the official result; and
- exit advantage, defined as actual net P&L minus hold-to-settlement net P&L.

A positive exit advantage means the exit saved money relative to holding; a negative value means the exit cost
money. The protected production status reports resolved and pending comparisons, aggregate actual and hold P&L,
helped/hurt counts, and the ten most recent market-level records. This audit submits no orders and does not change
the frozen entry, sizing, or exit rules.

The production client contains no transfer or withdrawal method. Funding is a separate one-time commissioning
operation. Production status is password protected at `/api/production/status` and `/production`.

## Evidence limits

The real-money pilot was authorized before the preregistered promotion studies completed. The prior exact-arrival
production audit was negative: only 41 of 152 settled demo fills qualified against production quotes, and those
41 lost $2.1620 before adverse-price stress. Demo profits therefore must not be treated as expected live returns.
Candidate Study 003 and Risk Sizing Audit 001 continue without parameter changes.
