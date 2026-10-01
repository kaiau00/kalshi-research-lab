# Parameter Study 004 protocol

Declared October 1, 2026 before Study 004 reads archived events. This is a development-only chronological robustness search over the frozen v6 prefix from segment 0 through segment 4,344, dataset `e2d5cb33e7c44660809b531f03d4b4e3`, ending at digest `cf620d41eb95df0912d1a26ec1708d9545a821dbb3a3442647f09bab8055f786`. Results from this prefix have already been viewed for earlier strategies, so no Study 004 result is an untouched validation claim.

The existing `adaptive_volatility` Kalshi demo runner and prospective Candidate Study 003 remain unchanged. Study 004 is simulated research with no order-submission path.

## Shared execution model

- BTC `KXBTC15M` only, independent $100 account per configuration and maximum $1 modeled cost per market.
- Adaptive-volatility forecast, official outcomes, recorded fee metadata, recorded local receipt order, two-sided book freshness and 500 ms delayed IOC execution.
- Both outcomes are eligible. An entry requires modeled probability minus ask and fee to meet the configuration's edge threshold.
- At most three attempts ten seconds apart, no reentry after a fill, no maker-fill assumptions and no invented outcomes, prices or depth.
- Every result reports one- and two-cent adverse fill-cost stresses with fees recomputed at the stressed price.

## Fixed 40-configuration search

The five probability models are raw adaptive, symmetric calibration with coefficient `0.7459916645763038`, and raw adaptive blended with the executable market midpoint in log-odds space at market weights 25%, 50% and 75%.

The grid is deliberately staged instead of taking the full Cartesian product:

1. Twenty signal/edge configurations: each of five probability models at 4%, 6%, 8% and 10% minimum net edge, using the original 5–300 second entry window, no added spread cap and one qualifying quote.
2. Ten time-window configurations: each probability model at 6% minimum edge using 30–120 and 30–180 second windows, no added spread cap and one qualifying quote.
3. Four spread configurations: calibrated and 50% market blend at 6% minimum edge, a 30–180 second window, one qualifying quote, and maximum binary spread of 3 or 5 cents.
4. Six persistence configurations: calibrated and 50% market blend at 6% minimum edge, a 30–180 second window, two consecutive qualifying seconds, and maximum binary spread of 3, 5 or 7 cents. The selected side must match and its ask may move by no more than one cent.

Fast realized volatility at entry is recorded as the root-mean-square one-second log return over the latest 60 valid returns, in basis points. Reports stratify trades into fixed low (`<0.5` bp), medium (`0.5–1.5` bp) and high (`>1.5` bp) regimes. This study observes regimes but does not select a regime filter.

## Evaluation

Markets are assigned chronologically to five contiguous blocks with complete markets kept together. For each configuration, report net P&L after fees, P&L without the three largest winners, one- and two-cent stress P&L, settled trades, fill rate, positive-day share, cost-basis maximum drawdown, Brier score, binary log loss, calibration, volatility regimes and per-block P&L.

A configuration is promotion-eligible only if it has at least 100 settlements, positive net P&L, positive P&L without its three largest winners, positive two-cent-stress P&L, positive P&L in at least four of five chronological blocks, positive daily P&L on more than half of observed UTC dates, maximum drawdown no greater than $20 and binary log loss no worse than the raw 4% reference. Eligible configurations are ranked lexicographically by minimum block P&L, P&L without the top three winners, lower log loss and then number of settlements. If none passes, the study has no winner.

Any selected configuration must be frozen in a new prospective study beginning after a new cutoff. Study 003 remains an independent test of its four already registered definitions and cannot be rewritten to include a Study 004 selection.

## Persistence and limits

The exact configuration list, study source hash, dataset, terminal prefix, segment cursor, simulator state and reports are durable under `/data/parameter-studies/004`. Registration or source mismatch stops processing. A checkpoint is written at least every 25 segments and at completion; a restart may replay only the uncheckpointed suffix. Processing stops permanently after segment 4,344. Raw archived events remain unchanged.
