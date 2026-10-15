# Historical Parameter and Kelly Study 019 Result

Study 019 completed its preregistered 1,620-configuration signal grid and five-path sizing comparison on the
already-viewed first 80% of Dataset 017. Two closely related configurations passed every aggregate fixed-$1 gate.
The newest 20%, containing 3,463 markets, remains sealed and unevaluated. No demo or production order is
authorized.

The registration SHA-256 is `9ebb1607b3427f3c9a2b92937872aeb0affafbce4a3ae3f910083430f72b752e`.
The final machine-report SHA-256 is `8359eafa0292c1a3d331298768891af34aeb07beb08de868019547fcebdcaa8a`.

## Signal result

The selected research configuration is `w00_e030_p5085_g060_t300_s02_b00`:

- raw adaptive probability, with no interpolation toward Kalshi's midpoint;
- at least 3% modeled net edge;
- selected-side ask from $0.50 inclusive to $0.85 exclusive;
- raw-model-versus-market YES probability gap no greater than 6%;
- entry at a completed candle ending 60 through 300 seconds before close;
- binary spread no greater than two cents; and
- nonnegative selected-side edge after adding two cents and the one-contract fee.

The second passer has identical rules except for a one-cent spread ceiling. This neighboring pass is better than a
single isolated winning cell, but only two of 1,620 searched configurations passed, so multiple-testing risk
remains substantial.

| Fixed-$1 signal | Trades | Wins | Net P&L | Ex top 3 | +1 cent | +2 cents | Positive days | Positive blocks | Drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Selected, 2-cent spread | 549 | 415 | +$11.9751 | +$10.5276 | +$6.6574 | +$1.3466 | 79/147 | 4/5 | $6.5425 |
| Neighbor, 1-cent spread | 520 | 391 | +$10.3083 | +$8.8608 | +$5.2700 | +$0.2382 | 75/147 | 4/5 | $6.0944 |
| Original conservative baseline | 78 | 64 | +$2.4125 | -$0.1558 | +$1.6446 | +$0.8778 | 47/147 | 4/5 | $3.3582 |

The selected signal's five market-time blocks made $2.6974, -$1.5654, $7.0945, $2.6714 and $1.0772. Entries
averaged $0.7206 and ranged from $0.50 to $0.84. There were 294 NO and 255 YES trades. Because every price is at
least $0.50, fixed-$1 sizing bought exactly one contract per decision.

The original conservative baseline still fails: it has fewer than 100 trades, fewer than half of dates positive,
and negative P&L after removing its three largest winners. The grid's main improvements were excluding asks below
$0.50, reducing the modeled edge threshold from 4% to 3%, and allowing a two-cent spread.

## Time-split and uncertainty warning

The aggregate selected signal made $8.8898 across 370 original-development trades and $3.0853 across 179 later
original-validation trades. Both periods remained positive after removing their three largest winners. However,
the later period's two-cent-stressed result was -$0.3789, compared with +$1.7255 in development. That weakens the
case that the remaining $1.3466 aggregate stress profit is stable.

The selected signal's mean daily P&L was about $0.0815, with a simple normal 95% interval from approximately
-$0.0476 to +$0.2106. This interval includes zero and does not adjust for testing 1,620 correlated configurations.
The result is a candidate, not proof of a positive expectation.

## $100 bankroll and Kelly result

Every path started with $100. Kelly used current cash, integer contracts, fees inside the target budget and a $3
maximum per market. Stress preserves the base quantity.

| Sizing | Ending cash | Net P&L | Ex top 3 | +2-cent P&L | Max drawdown | Mean target | Times capped |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Fixed $1 | $111.9751 | +$11.9751 | +$10.5276 | +$1.3466 | $6.5425 | $1.00 | N/A |
| Fixed $3 | $143.4316 | +$43.4316 | +$36.1941 | +$5.2291 | $24.1941 | $3.00 | N/A |
| Eighth Kelly, $3 cap | $124.0070 | +$24.0070 | +$21.1720 | +$0.3795 | $13.5607 | $2.06 | 89/549 |
| Quarter Kelly, $3 cap | $138.4251 | +$38.4251 | +$32.0684 | +$2.4817 | $22.5169 | $2.88 | 426/549 |
| Half Kelly, $3 cap | $143.4316 | +$43.4316 | +$36.1941 | +$5.2291 | $24.1941 | $3.00 | 549/549 |

Half Kelly is identical to fixed $3 because it hit the cap on every decision. Quarter Kelly hit the cap on 78% of
decisions, so it was mostly a fixed-$3 strategy as well. Eighth Kelly was more adaptive, but its two-cent-stressed
profit fell to only $0.3795 while drawdown more than doubled relative to fixed $1.

Kelly did not reveal a superior risk-adjusted choice. Fixed $1 retained the smallest drawdown and the clearest
margin under adverse price. Larger sizing amplified the same quote-screen result and increased maximum drawdown to
13.6–24.2% of the starting bankroll. Since the probability model has not passed an untouched holdout and the
archive cannot prove fills, the larger headline Kelly and fixed-$3 returns do not justify larger live risk.

## Decision

The selected signal is frozen as the only Study 019 candidate eligible for a separately preregistered holdout
test. The holdout was not opened automatically. The recommended sizing remains fixed $1 for any future research
comparison. A holdout pass would still require forward executable-book validation before live trading.

The complete local machine report is `reports/historical-parameter-kelly-study-019.json`. A tracked
[sanitized machine summary](validation/historical-parameter-kelly-study-019-summary.json) preserves the baseline,
both passing configurations, all sizing results, the original-partition diagnostic and report hashes.
