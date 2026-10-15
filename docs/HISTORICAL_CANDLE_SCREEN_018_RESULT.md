# Historical Candle Strategy Screen 018 Result

Study 018 is complete on its preregistered development and validation partitions. The newest 20% holdout remains
sealed and unevaluated. No strategy passed the frozen advancement gate, so this result does not justify opening
the holdout or enabling an order path.

## Data and execution interpretation

The source is the fixed Dataset 017 archive: 17,311 settled `KXBTC15M` markets from April 15 through October 15,
2026. The database SHA-256 is
`31623b3a178d276bbc5fb0d8ab87600d90dfba7da98ead1099010ef0438a2d7f` and the audit SHA-256 is
`dd361ab7ce8caed0c3861ce7953840d8034415046fcc78575a446c2bce755610`. The Study 018 registration SHA-256 is
`1d96cf51cfad243430c93bc76e70cb4c5e77c6f46c102f6ca540f8089e03a2c0`.

The chronological split assigned 10,386 markets to development, 3,462 to validation and 3,463 to the locked
holdout before exclusions. There were 10,339 eligible development markets across 110 UTC dates and 3,454 eligible
validation markets across 37 dates. The fixed audit exclusions removed 47 unique development markets and eight
validation markets. The screen loaded 12,464,830 top-of-second BRTI values and verified both source checksums
before calculating P&L.

Each partition starts with an independent $100 reference balance. Entries use a completed one-minute closing ask,
integer contracts, the quadratic taker fee and a fixed $1 all-in maximum. The one- and two-cent columns add adverse
price to the same quantity. Minute candles do not contain depth, queue position or the book 500 ms later, so these
are quote-screen results rather than executable-fill results.

## Fixed comparison

Dollar P&L is after modeled entry fees. `Ex top 3` removes the three largest winning trades from validation.

| Strategy | Development trades | Development P&L | Validation trades | Validation P&L | Ex top 3 | +1 cent | +2 cents |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `basic_fair_value` | 3,466 | -$99.9966 | 1,096 | -$99.9916 | -$168.0565 | -$170.4274 | -$240.7710 |
| `tail_underdog` | 1,182 | +$13.1614 | 330 | +$1.1349 | -$37.9628 | -$20.5976 | -$42.3019 |
| `adaptive_volatility` | 4,628 | -$99.9992 | 1,884 | -$23.2437 | -$114.3005 | -$122.9563 | -$222.5349 |
| `market_agreement_band_001` | 1,552 | -$16.6804 | 829 | -$14.6112 | -$20.7789 | -$23.7346 | -$32.8420 |
| `market_anchor_conservative_001` | 52 | -$0.3734 | 24 | +$3.3411 | +$0.8018 | +$3.0899 | +$2.8395 |
| `moderate_disagreement_band_001` | 21 | -$2.8466 | 16 | -$2.9475 | -$6.7112 | -$3.2936 | -$3.6393 |

## What the result establishes

The broad basic and adaptive signals fail badly. The basic account nearly exhausts its independent $100 balance
in both partitions. Adaptive also exhausts the development balance and loses $23.2437 in validation. In selected
validation trades, Kalshi's midpoint has better Brier score and log loss than either broad raw model. A four-point
modeled edge is therefore not reliable evidence of a real edge in this archive.

The tail strategy's small positive headline does not survive robustness tests. Its validation P&L is +$1.1349,
but becomes -$37.9628 after removing its three largest winners and is negative with one cent of adverse price.
Its maximum drawdown is $49.2199, and only three of five chronological blocks are positive. Cheap contracts create
large quantities inside a $1 cost cap, so a few payouts dominate the result.

The conservative anchor is the only validation result that remains positive after removing the three largest
winners and under both price stresses. It produces +$3.3411 from 24 trades, including 21 wins, with a $0.8495
maximum drawdown. That is encouraging but insufficient: development is slightly negative, only three of five
validation blocks are positive, fewer than half of validation dates are positive, and 24 trades is far below the
100-trade gate. Its validation entries also average $0.7817, so the result depends on a sparse set of heavily
favored contracts.

Moderate disagreement loses in both partitions. The broader market-agreement filter has hundreds of trades but
also loses in both partitions and under every stress test. Neither warrants further holdout evaluation in its
current form.

Every strategy fails at least one frozen gate. The locked 3,463-market holdout therefore remains unused. The
machine-readable local report is `reports/historical-candle-screen-018.json`, with report SHA-256
`b060d852332ac25a1680fc57fe0078eafcfd1a8e83c4a456acea9690644870ad`.
