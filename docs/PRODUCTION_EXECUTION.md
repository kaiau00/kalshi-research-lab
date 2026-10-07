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
- Execution: 500 ms delayed IOC, at most three attempts and one fill per ticker
- Exit: official settlement; no early exit

## Required deployment guards

Production execution starts only when `LAB_PRODUCTION_ENABLED=1` and
`LAB_PRODUCTION_AUTHORIZATION=real-btc-15m-adaptive-3usd-2026-10-07`. The application refuses to run demo and
production execution simultaneously. The account must initially expose exactly $100 on exchange index 2 and no
positions or resting orders.

Before every submission, the runner verifies exchange and shard status, account cash, the absence of any nonzero
shard-2 position or resting order, a fresh production order book, and that the original limit remains marketable
at the modeled arrival time. It writes the intent with SQLite `synchronous=FULL` before the POST. There are no
automatic POST retries. An unknown request result blocks later orders until the exact client order ID is found.

The production client contains no transfer or withdrawal method. Funding is a separate one-time commissioning
operation. Production status is password protected at `/api/production/status` and `/production`.

## Evidence limits

The real-money pilot was authorized before the preregistered promotion studies completed. The prior exact-arrival
production audit was negative: only 41 of 152 settled demo fills qualified against production quotes, and those
41 lost $2.1620 before adverse-price stress. Demo profits therefore must not be treated as expected live returns.
Candidate Study 003 and Risk Sizing Audit 001 continue without parameter changes.
