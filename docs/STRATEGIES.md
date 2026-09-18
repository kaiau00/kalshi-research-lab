# Initial experiment definitions

All defaults are versioned in `src/research_lab/settings.py`. This is a starting specification, not an optimized configuration.

| Model | Hypothesis | Entry filter |
|---|---|---|
| Basic fair value | The market sometimes differs from a simple benchmark-average probability model | Either outcome, 5–300 seconds left, estimated edge after fees at least 4 percentage points |
| Tail underdog | A cheap outcome close enough to the threshold is occasionally underpriced near expiry | Same probability model, 5–135 seconds left, cheaper ask no more than 35 cents, absolute modeled z-score no more than 1, same edge gate |
| Adaptive volatility | Recent volatility changes matter more than the longer baseline | Same entry gates as basic fair value, variance blended 70% recent 60 seconds and 30% longer 600 seconds |

All use up to $1 per market including assumed taker fees, a $100 independent bankroll, 500 ms arrival latency, at most three attempts spaced ten seconds apart, and at most one filled entry per market. A partial IOC closes the remainder. There are no exits before official settlement, compounding position rules, Kelly sizing, or optimization loops.

## Probability model

Use contiguous one-second log returns from BRTI only, with at least 60 returns. No forward-filled gaps, spot-exchange substitute, or forced minimum volatility. For the settlement average, use the 60 source seconds in `[close − 60 seconds, close)`. Any missing already-observed settlement second blocks the forecast.

The conditional mean averages known settlement observations and the latest benchmark price for remaining seconds. Conditional variance uses Brownian covariance `min(t_i, t_j)` across remaining sampling times. A normal CDF estimates the chance of crossing the threshold, with a half-cent continuity correction for the specified cent rounding. This approximation assumes zero short-horizon drift and locally stable diffusion; it does not model jumps, latency arbitrage, or volatility risk premiums.

## Execution assumptions requiring live-data audit

Book messages are requested with `use_yes_price=true`; NO levels are converted to their own outcome bid scale exactly once. YES asks come from `1 − NO bid`, and vice versa. A snapshot is required after sequence loss or reconnection. Books older than two seconds and benchmark observations older than three seconds block entries.

An order uses the book known at the first recorded event at or after modeled arrival. It may fill only at the best available level at or below its limit. This sampling convention can bias fills in either direction; it must be stress-tested against actual timing. Depth is not a guarantee another trader did not take it. There is no queue-position simulation. Positions cannot spend reserved cash, and the engine never fills a 40-cent limit at 55 cents.

The default fee coefficient is 0.07 and balance precision is $0.0001. Calculations round the modeled fee up to six decimals, then the aggregate debit to the configured balance precision. The simulator uses one aggregate price level; exchange multi-fill rounding and account-specific rounding require comparison with the actual account rules. Market/series fee overrides and changes must be checked before interpreting profitability. There is no infrastructure-cost deduction from trade P&L; include the separate Railway cost when assessing economic usefulness on $100.

The collector records series fee metadata every fifteen minutes and event metadata approximately every minute. New decisions and pending fills require event metadata no older than two minutes and series metadata no older than thirty minutes. Event overrides take precedence; missing, stale or unsupported fees and inactive markets block simulated orders. These guards apply to the new v5 registration; older data was not retroactively supplemented. Missing fee metadata, a non-quadratic schedule, or a multiplier that exceeds the configured fee assumption blocks new simulated entries. The public `KXBTC15M` series check during the build returned `fee_type=quadratic` and `fee_multiplier=1`. This check does not establish the user's account-specific balance rounding.

## Primary sources checked during initial build

- [Kalshi order direction and YES price convention](https://docs.kalshi.com/getting_started/order_direction)
- [Order-book snapshots and deltas](https://docs.kalshi.com/websockets/orderbook-updates)
- [BRTI feed and final-window averages](https://docs.kalshi.com/websockets/cfbenchmarks-value)
- [Fee rounding](https://docs.kalshi.com/getting_started/fee_rounding)
- [Recent candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks)
- [Historical data and cutoff](https://docs.kalshi.com/getting_started/historical_data)

The exact current market rules are preserved with every metadata observation. If a market's rules or schema differ from the supported form, the integration must be reviewed rather than silently guessed.

Settlement boundary was corrected on 2026-09-17 after all 15 audited completed markets matched the close-exclusive average, while the former close-inclusive model matched none. Kalshi’s `last_60s_windowed_average_15min` feed field uses the latter boundary and must not be treated as the official settlement average. See `DATA_VALIDATION.md`. Existing reports from the earlier model are commissioning artifacts; corrected forward experiments require a new registration.
