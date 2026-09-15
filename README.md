# Kalshi Research Lab

A BTC-only, 15-minute market recorder and strategy research system. **No live-order capability.**
The purpose is to reject weak ideas and measure promising ones, not to promise a return on $100.

## What is implemented

- Raw market metadata, authenticated order-book updates, public trades, and official BRTI index observations, stored in receipt order with a SHA-256 chain.
- Independent $100 paper accounts for basic fair value, a late underdog near the threshold, and adaptive volatility. Each risks at most $1 including modeled entry fees per market.
- One execution model: delayed IOC buys, available best-level depth, integer contracts, limit-price enforcement, fees, reserved cash, and official outcome settlement. No assumed maker fills.
- Historical minute-quote download and screening in a separate database. These do **not** claim fills or executable returns.
- Frozen data-prefix replay, source/config hashes, chronological market-level 60/20/20 partitions, explicit holdout disclosure, calibration and daily bootstrap uncertainty when the sample is large enough.
- A password-protected dashboard, fresh-data readiness, persistent SQLite storage, and hourly replay of the fixed strategy definitions registered before collection started.

The initial strategies are hypotheses. The underdog filter alone is not an edge: its estimated probability must exceed the executable quote plus assumed fees and a margin. A Gaussian forecast can be wrong, especially near expiry or during jumps. The three models are related, not three independent discoveries.

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

See [build plan](docs/BUILD_PLAN.md), [operating guide](docs/OPERATIONS.md), [strategy assumptions](docs/STRATEGIES.md), and [work log](docs/WORK_LOG.md).
