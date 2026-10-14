# Market Calibration Study 010 development protocol

Declared on 2026-10-13 before implementing or calculating Study 010 P&L. This is a read-only development study and
cannot submit an order, remove the production pause or promote itself.

## Question

Does a small, expanding-window calibration of Kalshi's own midpoint identify favorite-side prices that remain
positive after the actual spread, fee, 500 ms arrival, displayed depth and two cents of adverse-price stress?

Study 008 found that Kalshi's midpoint beat the raw adaptive and pooled models on 643 eligible decisions. Study 010
therefore uses the market as the entire probability input. It does not use the failed raw model to choose a side.

## Development source and tape

- Dataset `e2d5cb33e7c44660809b531f03d4b4e3`.
- Seed immediately before segment 4,345, with predecessor digest
  `cf620d41eb95df0912d1a26ec1708d9545a821dbb3a3442647f09bab8055f786`.
- Development segments 4,345 through 7,636 inclusive, ending at digest
  `7700cb0359bef4d775dae80b8fb2c0fb26a29a97332e7b5d2e21bd34bded504b`.
- Scheduled decisions at 300, 180, 60 and 30 seconds before close.
- Each row requires a fresh two-sided book, supported fee metadata, a fresh BRTI observation, an official result
  and the first recorded quote at or after 500 ms modeled arrival.

This source has already been inspected by other studies. Every result is development evidence.

## Models

The identity baseline is the two-sided Kalshi YES midpoint. The beta calibration is

```text
logit(p_cal) = c + a log(p_market) - b log(1 - p_market).
```

Penalized logistic regression shrinks `(c,a,b)` toward the identity `(0,1,1)`. Fit only outcomes officially
settled before the evaluation UTC day. Require five prior UTC dates and 250 distinct-market training rows.

Compare exactly two calibrators:

1. `market_beta_global_010`: fit one model from one canonical 180-seconds-left row per training market;
2. `market_beta_time_010`: fit a separate model for each registered decision offset, using one row per market.

The approximate penalized Hessian supplies a one-sided 90% probability lower bound. Report the identity market
probability even when a calibrator cannot meet its training requirement.

## Frozen simulated entry

- Select the side favored by the decision-time Kalshi midpoint; ties are rejected.
- Require selected-side decision ask below $0.95.
- Require the lower 90% calibrated probability bound to be at least the decision ask plus two cents plus the
  modeled one-contract fee.
- The first qualifying scheduled decision consumes that market, even if the arrival IOC is unmarketable.
- Use the decision ask as the IOC limit and observe the first book at or after 500 ms.
- Cap quantity to displayed best-level integer depth and a fixed $1 all-in simulated cost.
- Hold any simulated fill to the official result; no exit.

## Development screen

Report probability metrics on every eligible row and trading metrics separately for both calibrators. A model may
advance to a new immutable prospective registration only if it beats the identity midpoint on Brier score and log
loss, has at least 50 settled fills, positive P&L, positive P&L without its three largest winners, positive one- and
two-cent stress, positive results on more than half of UTC dates and in four of five chronological blocks, and no
unresolved exposure. Development success does not authorize demo or production orders.
