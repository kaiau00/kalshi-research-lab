# Kalshi Research Lab

A BTC-only, 15-minute market recorder, strategy research system, and tightly scoped execution service. The
authorized production pilot is limited to one adaptive-volatility strategy on Kalshi's BTC 15-minute markets,
with a $100 bankroll baseline and a fixed $3 maximum per market. The purpose is to reject weak ideas and measure
promising ones, not to promise a return on $100.

## What is implemented

- Raw market metadata, authenticated order-book updates, public trades, and official BRTI index observations, stored in receipt order with a SHA-256 chain.
- Independent $100 research accounts for basic fair value, a late underdog near the threshold, and adaptive volatility. The original fixed comparison risks at most $1 including modeled entry fees per market. The currently running adaptive-volatility demo account uses a fixed maximum risk of $3 per market.
- One execution model: delayed IOC buys, available best-level depth, integer contracts, limit-price enforcement, fees, reserved cash, and official outcome settlement. No assumed maker fills.
- Historical minute-quote download and screening in a separate database. These do **not** claim fills or executable returns.
- Frozen data-prefix replay, source/config hashes, chronological market-level 60/20/20 partitions, explicit holdout disclosure, calibration and daily bootstrap uncertainty when the sample is large enough.
- A password-protected dashboard, fresh-data readiness, persistent SQLite storage, and hourly replay of the fixed strategy definitions registered before collection started.
- Separate demo and production adapters and ledgers. Railway refuses to start both execution adapters together.

The initial strategies are hypotheses. The underdog filter alone is not an edge: its estimated probability must exceed the executable quote plus assumed fees and a margin. A Gaussian forecast can be wrong, especially near expiry or during jumps. The three models are related, not three independent discoveries.

## Adaptive-volatility strategy math

The adaptive strategy estimates the chance that the official final-minute BRTI average will finish
above the market threshold. It does not forecast a short-term trend. Its expected future BTC price is the latest
BRTI observation, with uncertainty estimated from recent one-second returns.

For consecutive one-second BRTI prices, calculate log returns:

```text
r_t = ln(P_t / P_(t-1))
```

Calculate the mean squared return over the most recent 60 seconds and 600 seconds, then blend them:

```text
v_fast = mean(r_t^2 over 60 seconds)
v_slow = mean(r_t^2 over 600 seconds)
v       = 0.70 * v_fast + 0.30 * v_slow
```

The strategy requires at least 60 usable returns. It does not subtract an estimated drift or impose an artificial
volatility floor. The heavier 60-second weight is what makes the volatility estimate adaptive.

The contract settles on the average of the 60 BRTI source seconds in `[close - 60 seconds, close)`. Already
observed settlement-window prices are known. Each unobserved second has conditional expected price equal to the
latest BRTI price `S`, so the expected settlement average is:

```text
mu = (sum(observed settlement prices) + future_second_count * S) / 60
```

Let `F` be the unobserved source seconds and let `h_i` be the time from the latest observation to future second
`i`. The Brownian approximation accounts for correlation between future prices:

```text
C     = sum over i,j in F of min(h_i, h_j)
sigma = S * sqrt(v * C) / 60
```

For threshold `K`, the model applies a half-cent continuity correction to match the contract's strict or inclusive
comparison, then converts the standardized distance into a probability with the normal CDF:

```text
K_effective = K - 0.005  for greater-than-or-equal contracts
K_effective = K + 0.005  for strictly-greater-than contracts
z           = (mu - K_effective) / sigma
p_yes       = Phi(z)
p_no        = 1 - p_yes
```

For each side, let `q` be its best ask. The modeled quadratic taker fee for `n` contracts is:

```text
fee(n, q) = 0.07 * n * q * (1 - q)
```

The implementation rounds fees and total debits conservatively to the configured account precision. It evaluates
the best side using the one-contract all-in cost:

```text
edge = p_side - (q + fee(1, q))
```

An entry requires at least `0.04`, or four percentage points, of modeled edge after fees. It must also have 5 to
300 seconds remaining, fresh BRTI and order-book data, a supported fee schedule, and a valid two-sided quote.
The strategy buys the largest integer number of contracts whose price plus fees fits within the fixed $3 maximum:

```text
n = max integer n such that n * q + fee(n, q) <= $3
```

There is no Kelly sizing and no early exit. A filled position is held through the official finalized outcome. The
research execution model uses a 500 ms arrival delay, limit-price enforcement, and displayed best-level depth.
The production runner waits until the declared 500 ms arrival time, verifies that the original limit is still
marketable against a fresh production book, and submits an IOC order. It never creates a resting order or retries
an order POST. It writes a durable intent first and blocks all further orders if the request cannot be reconciled.

This probability is a model estimate, not a guaranteed edge. It assumes zero short-horizon drift, locally stable
diffusion, and approximately normal price movement. Jumps, regime changes, BRTI/market timing differences, and
miscalibration can make its probability wrong.

The latest production-equivalence audit found that the strong demo P&L did not transfer to the production order
book. Of 152 settled demo fills with exact production arrival snapshots, only 41 met the unchanged production
edge, fee, quote, and depth rules. Those 41 produced -$2.1620 at displayed production quotes, -$4.5052 with one
cent of adverse movement, and -$6.8328 with two cents. This is evidence against treating demo-account returns as
live-account expectations. See [Live-equivalence audit 002](docs/LIVE_EQUIVALENCE_AUDIT_002.md).

The user authorized the real-money pilot despite that negative audit. That decision does not promote the strategy
or prove an edge. Candidate Study 003 and Risk Sizing Audit 001 remain independent, frozen research studies.

## Run locally

Python 3.12 and uv are required. From this repository:

```sh
uv sync --locked
uv run ruff check .
uv run pytest
uv run research-lab demo --output reports/demo
```

The demo refuses to overwrite a dataset. Its report is conspicuously synthetic; its generated prices and outcomes are artificial and have no performance meaning. On a Python installation that does not load editable `.pth` imports, use `uv sync --locked --no-editable` and `uv run --no-editable ...`.

To run the real collector and dashboard, set the variables from `.env.example` in your shell or Railway, then:

```sh
uv run research-lab serve
```

Visit `http://localhost:8000`; username is `lab`, password is `LAB_DASHBOARD_PASSWORD` (minimum 16 characters). Without a password the dashboard stays closed. Without Kalshi credentials, public metadata collection works and the dashboard says `waiting for credentials`; `/readyz` returns 503. `/healthz` checks the worker, not trading-data readiness.

## Backtest versus forward paper

```sh
uv run research-lab history --db data/history-01.sqlite3 --days 2 --max-markets 192
uv run research-lab screen --db data/history-01.sqlite3 --output reports/history-01.json
uv run research-lab verify --db data/events.sqlite3
uv run research-lab backtest --db data/events.sqlite3 --split train --output reports/train
uv run research-lab backtest --db data/events.sqlite3 --split validation --output reports/validation
uv run research-lab backtest --db data/events.sqlite3 --split forward --output reports/forward
```

History has minute quotes and outcomes, not a time-accurate book or BRTI path. It can show whether cheap outcomes won more often than their quoted prices suggest, but cannot test the distance-to-threshold filter or establish a realizable return.

Recorded-data replay processes only events already received at each simulated decision. Forecasts use the official threshold, the observed part of the final-minute benchmark average, and a conditional model for remaining seconds. The final outcome comes from the official market result, never the model.

At the start of a fresh collector database, the default configuration and source hash are registered. `--split forward` only succeeds with those same definitions. Replaying this growing dataset reconstructs the fixed paper accounts across restarts; it is not submitting exchange paper orders. A code/config change requires a **new dataset**, and the earlier dataset remains available for exploratory replay. Reports disclose execution assumptions. Actual authenticated feed behavior still needs commissioning with your key.

## Compare ideas without fooling ourselves

1. Collect complete markets through multiple market conditions. Audit dropouts, benchmark freshness, thresholds, and official outcomes first.
2. Freeze a database prefix (`--end-id`) and save its report manifest. Use that identical prefix for every comparison; splitting a larger dataset later changes boundaries.
3. Explore training data. Change a small, predeclared set of settings through `--config experiment.json`. Keep all runs, including failures.
4. Compare on validation using fees, fills, net P&L, tied-up cash, calibration, and unresolved markets. Stress latency and fee assumptions. Do not rank by win rate alone.
5. Only after choosing a fixed configuration, disclose the holdout with `--split holdout --unlock-holdout`. Any further tuning makes that data exploratory. The flag records disclosure; it is an operational guard, not tamper-proof access control.
6. Require another fixed forward collection period before considering a live pilot. No result here automatically enables trading.

The initial hourly comparison is a preregistered forward benchmark across the three fixed models. Its results are visible, so those same markets must not subsequently be described as an unseen holdout for a model selected from that comparison.

Open positions are shown at cost for drawdown, **not** liquidation value. Reports retain unavailable outcomes and locked capital. Confidence intervals remain unavailable below 20 observed UTC days and 50 settled markets; reaching those counts alone is not proof of an edge. Daily resampling does not account for all serial dependence or multiple testing.

See [production execution](docs/PRODUCTION_EXECUTION.md), [build plan](docs/BUILD_PLAN.md), [operating guide](docs/OPERATIONS.md), [strategy assumptions](docs/STRATEGIES.md), and [work log](docs/WORK_LOG.md).
