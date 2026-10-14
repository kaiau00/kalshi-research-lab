# Databento Futures Overlay Study 016 development protocol

Declared on 2026-10-13 before calculating any result from the Databento features. This is a read-only,
development-only study. The Kalshi outcomes and aggregate performance of the source period have already been
viewed, so no result is untouched validation and no result can authorize demo or production orders.

## Question

Did causal CME Bitcoin-futures momentum and realized volatility contain incremental information about the
official KXBTC15M outcome beyond the archived adaptive model probability?

This study is an information and selection audit. CME futures are neither the BRTI settlement source nor an
executable Kalshi quote. They may filter an already recorded Kalshi fill, but they may not create an opposite-side
fill or replace the recorded Kalshi arrival price, fee, depth, or official result.

## Frozen sources

- Kalshi source: the `adaptive_volatility` closed trades in
  `data/settlement-research-input/seed-checkpoint.json`, file SHA-256
  `055195a302b02cee21fb9ce99b9fe0a2dbbdd22ebce580221f4c8ef056d1b57b`.
- Source is the already disclosed v6 development prefix ending immediately before segment 4,345.
- Databento dataset `GLBX.MDP3`, schema `ohlcv-1m`, continuous symbols `BTC.c.0` and `MBT.c.0`.
- Databento interval: `2026-09-20T00:00:00Z` through `2026-10-13T18:00:00Z`.
- `BTC.c.0` is primary. `MBT.c.0` is a prespecified robustness replication.

The raw DBN chunks, derived CSVs, query interval, file hashes and validation counts remain in the ignored
`data/external/databento` directory. Credentials must never enter the report, source tree, Git or logs.

## Causal feature clock

Databento minute-bar timestamps identify the start of a minute. At a Kalshi decision, the latest usable futures
bar must end before the archived Kalshi decision time. A feature is unavailable if the most recent completed bar
is more than two minutes old, if a required lookback endpoint is more than two minutes stale, or if fewer than 80%
of the expected bars exist in the 60-minute lookback. Missing features remain missing; weekend and maintenance
gaps are not forward-filled.

Calculate log returns over 5, 15 and 60 minutes and realized variance over 15 and 60 minutes. For a recorded NO
selection, multiply each directional return by -1 so a positive signed return means agreement with the selected
side. The fourth fitted feature is `log(RV_15 / RV_60)` with a fixed numerical floor of `1e-12`.

## Frozen comparisons

Evaluate both symbols independently with expanding UTC-day training. Fit only trades officially settled before
the evaluation day's start. Require at least three prior decision dates and 150 feature-complete training trades.
Standardize the four features using the training prefix only.

Compare exactly three selected-side probability models:

1. the archived adaptive probability;
2. a calibration control, `logit(p) = alpha + gamma * logit(p_adaptive)`;
3. the futures overlay, adding the four standardized Databento features to the calibration control.

Fit penalized logistic regression with L2 penalty 25, shrinking `(alpha, gamma)` toward `(0, 1)` and all futures
coefficients toward zero. The inverse penalized Hessian supplies a one-sided 90% lower probability bound using
`z = 1.281551565545`.

Also report two fixed, non-fitted filters on every feature-complete source trade: selected-side agreement with
both 5- and 15-minute returns, and the same rule while the 60-minute return is not opposing. These filters are
diagnostics and do not compete with the primary fitted overlay.

## Frozen execution counterfactual

The fitted trading comparison may only reject an archived adaptive fill. It reuses that fill's recorded side,
arrival price, maximum observed filled quantity, fee schedule and official outcome. Size to the largest integer
quantity whose all-in entry cost is at most $1 and never exceed the recorded filled quantity. Hold to official
settlement.

A model selects the fill only when its one-sided 90% probability lower bound is at least the actual one-contract
all-in arrival cost plus two cents. Report net P&L after fees, P&L without the three largest winners, one- and
two-cent adverse-price stress, positive-day share, five chronological blocks, maximum cost-basis drawdown,
probability calibration and all coverage exclusions.

## Development screen

The primary `BTC.c.0` overlay passes only if it has at least 100 settled selections; beats both the raw adaptive
probability and calibration control on Brier score and log loss; has positive P&L, positive P&L without its three
largest winners and positive one- and two-cent stress; is positive on more than half of evaluated UTC dates and in
four of five chronological blocks; and has no unresolved exposure. The `MBT.c.0` replication must point in the
same direction on probability quality and stressed P&L. Any passing result would justify only a new immutable
prospective registration.

