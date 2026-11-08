# Weather Study 032 — earlier-horizon calibration screen

Run November 7, 2026 using the immutable NWS-rule price archives and the
existing 91-of-91 exact NCEI/Kalshi final-value alignment gate. This is an
exploratory displayed-ask screen, not an executable backtest: it has no depth,
queue position, or actual-fill inference.

## Fixed screen

- Decision horizons: 1, 2, 4, and 8 hours before market close.
- Fee: `ceil(0.07 * price * (1 - price), 6 decimal places)` per one-contract
  indicative taker fill.
- Stress: one cent worse ask; observations that reach $1.00 are excluded from
  the stressed total.
- Chronological split: 28 development dates through July 2, then 19 validation
  dates.

The archive includes 546 NWS-rule contracts over the 91 aligned dates. Because
many old contracts were already one-sided or lacked a fresh qualifying candle
at a decision time, the screen retained only 222 displayed quote observations.
They are correlated contract-side observations, not 222 independent trades.

## Aggregate result

| Horizon | Development quotes / indicative P&L / 1¢ stress | Validation quotes / indicative P&L / 1¢ stress |
| --- | ---: | ---: |
| 1 hour | 4 / -$0.0454 / -$0.0854 | 4 / -$0.0242 / -$0.0640 |
| 2 hours | 4 / -$0.1143 / -$0.1543 | 0 / not observable / not observable |
| 4 hours | 8 / -$0.1572 / -$0.2370 | 4 / -$0.0348 / -$0.0747 |
| 8 hours | 120 / -$2.0040 / -$3.2011 | 78 / -$1.1177 / -$1.8962 |

The only horizon with even modest coverage, eight hours, is negative in both
chronological partitions and becomes more negative under the one-cent stress.
Some individual price bands were positive, but have two or three observations
or reverse across partitions. Selecting one would be parameter mining.

## Decision

No weather candidate is selected. This data does not support a taker strategy
at the tested horizons. The next weather improvement must be a new,
pre-specified hypothesis with richer source-aligned intraday weather state and
meaningfully broader historical price coverage—not a band search over this
screen.
