# Historical Candle Strategy Screen 018

Declared on 2026-10-15 before calculating any strategy P&L from Dataset 017. This is a read-only historical
screen. It cannot submit an order, resume production or establish that a historical IOC would have filled.

## Fixed source and split

The source is the completed `KXBTC15M` Dataset 017 archive for 2026-04-15 through 2026-10-15. Its database
SHA-256 is `31623b3a178d276bbc5fb0d8ab87600d90dfba7da98ead1099010ef0438a2d7f`; its audit SHA-256 is
`dd361ab7ce8caed0c3861ce7953840d8034415046fcc78575a446c2bce755610`; and its final event-chain digest is
`03526f0e63396de6cd8ddf8df77bcddbd83aff4d0753daf3f4b5285232b7c70f`.

Sort all 17,311 source markets by `(close_time, ticker)` and split them chronologically 60% development, 20%
validation and 20% sealed holdout by count. Apply data-quality exclusions after assigning partitions so exclusions
cannot move the boundaries. Exclude markets identified by the fixed audit as lacking candles, a complete
settlement BRTI minute, numeric expiration metadata or a supported strike rule, plus the two material BRTI
reconstruction discrepancies. Keep the 122 one-cent rounding differences. The holdout is not opened in this run.

## Causal observations and execution limit

Evaluate only one-minute candle end timestamps with 5 through 300 seconds remaining. The quote is the YES bid and
ask close in that completed candle. The latest usable BRTI input is the top-of-second value at least one second
before the decision; every required return must be contiguous. The first qualifying decision consumes the market.

The base screen buys the selected side at its closing ask, includes the frozen quadratic taker fee, uses integer
contracts within a fixed $1 all-in cap and holds to Kalshi's official result. Recalculate P&L after adding one and
two cents to the same entry quantity. There is no historical depth, queue position or 500 ms arrival book, so the
base result is a quote screen and the stress results are price sensitivity. None is an executable-fill claim.

## Fixed strategies

Compare the six existing registered definitions without tuning:

1. `basic_fair_value`: 600-second variance and at least four percentage points of net modeled edge.
2. `tail_underdog`: basic model, cheaper side only, at most $0.35, at most 135 seconds left, absolute modeled
   z-score at most one and the same four-point edge.
3. `adaptive_volatility`: 70% weight on 60-second variance and 30% on 600-second variance, with the same edge.
4. `market_agreement_band_001`: adaptive source signal, $0.30–$0.95 ask, model-market gap at most 0.08 and spread
   at most $0.02.
5. `market_anchor_conservative_001`: adaptive source, $0.30–$0.85 ask, gap at most 0.06, spread at most $0.01,
   nonnegative two-cent stressed edge and its frozen cooldown/loss/drawdown controls.
6. `moderate_disagreement_band_001`: adaptive source, $0.30–$0.50 ask, model-market gap greater than 0.06 and at
   most 0.08, one-cent spread, nonnegative two-cent stressed edge and the same risk controls.

## Frozen review

Report settlements, wins, fees, net P&L, P&L without the three largest winners, one- and two-cent stress,
positive-day share, five chronological blocks, maximum drawdown, Brier score, log loss and all rejection counts.
A candidate may advance to the sealed holdout only with at least 100 validation settlements and 20 validation UTC
dates; positive P&L; positive P&L after removing its three largest winners; positive one- and two-cent stress;
more than half of validation dates positive; at least four of five blocks positive; and drawdown no greater than
$10. Passing would justify opening the holdout, not live trading.

The machine-readable registration in `src/historical_backtest/registration.py` is authoritative.

