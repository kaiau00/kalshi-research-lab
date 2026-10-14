# Databento Futures Overlay Study 016 result

Study 016 failed its frozen development screen. CME Bitcoin-futures features did not produce a robust executable
Kalshi edge on the archived adaptive fills. The result is development evidence from an already viewed period and
does not authorize demo or production orders.

## Coverage

The source contained 616 officially resolved `adaptive_volatility` fills from September 21–30, 2026. Features
required a completed futures bar, fresh 5/15/60-minute endpoints and at least 48 observed bars in the trailing
60 minutes. Missing CME weekend and maintenance data remained missing.

| Series | Feature-complete fills | Walk-forward evaluation | Dates |
|---|---:|---:|---:|
| CME Bitcoin future `BTC.c.0` | 184 | 33 | 1 |
| CME Micro Bitcoin future `MBT.c.0` | 348 | 166 | 5 |

The main-contract result is too small to support a conclusion. Its strict coverage and training gates left only
September 29 for evaluation. The micro contract provided the more useful robustness test.

## Probability result

| Series and model | Brier score | Log loss |
|---|---:|---:|
| `BTC.c.0` raw adaptive | 0.193105 | 0.575063 |
| `BTC.c.0` calibration control | 0.191200 | 0.569198 |
| `BTC.c.0` futures overlay | **0.187834** | **0.559191** |
| `MBT.c.0` raw adaptive | 0.175930 | 0.552906 |
| `MBT.c.0` calibration control | **0.172505** | **0.540456** |
| `MBT.c.0` futures overlay | 0.173822 | 0.542200 |

The small primary slice favored the futures overlay, but the larger replication did not. Calibration alone beat
both the raw adaptive probability and the futures overlay on the micro-BTC evaluation. The external futures
features did not add stable probability information beyond correcting the adaptive model's calibration.

## Executable-selection result

Every fitted selection reused the archived side, actual 500 ms arrival fill, fee and official result, with integer
quantity capped to $1 all-in cost. Entry required the one-sided 90% probability lower bound to clear actual
one-contract cost plus two cents.

| Series and selector | Trades | Wins | Net P&L | Without top three | +1 cent | +2 cents | Positive days | Positive blocks |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `BTC.c.0` calibration | 11 | 6 | -$3.5468 | -$3.9255 | -$3.7584 | -$3.9693 | 0/1 | 2/5 |
| `BTC.c.0` futures overlay | 10 | 5 | **-$3.6664** | -$4.0451 | -$3.8791 | -$4.0914 | 0/1 | 1/5 |
| `MBT.c.0` calibration | 37 | 11 | -$7.2861 | -$20.5478 | -$10.6768 | -$14.0621 | 0/5 | 2/5 |
| `MBT.c.0` futures overlay | 27 | 12 | **+$2.5540** | **-$9.8945** | +$1.0339 | **-$0.4839** | 1/5 | 2/5 |

The micro overlay's positive headline depended on its largest winners and disappeared under the frozen two-cent
stress. It also traded on only 27 markets and was positive on one of five evaluation dates.

The fixed momentum diagnostics also failed. Requiring selected-side agreement with 5- and 15-minute micro-BTC
returns lost $5.2163 across 119 trades; adding non-opposition from the 60-minute return lost $5.5608 across 74.
Both remained negative after adverse-price stress and after removing their three largest winners. The main-contract
versions were also negative.

## Decision

The registered primary screen failed. The undersized main-contract slice passed its probability comparisons but
failed every return gate. The larger micro-BTC replication failed the incremental-probability, concentration,
stress and consistency requirements.

Do not promote this overlay, fit another return horizon on the same dates or use its positive micro-BTC headline
to resume trading. The useful finding is narrower: day-ahead calibration improved the failed adaptive model,
while CME momentum and volatility did not add robust incremental value. A future external-price study would need
new untouched dates, better around-the-clock spot or BRTI-constituent coverage and a separately frozen model.

The complete machine-readable report, including every gate, exclusion, daily result, chronological block and
coefficient path, is in
[`validation/databento-futures-overlay-study-016-development.json`](validation/databento-futures-overlay-study-016-development.json).

