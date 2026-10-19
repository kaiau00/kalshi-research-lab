# Market-Shrunk Kelly Risk Study 024 Result

Study 024 compared risk rules on the exact 838 decisions made by Study 023's frozen signal. It started every
path with $100, included entry fees in each budget, used integer contracts, capped every Kelly path at $3 all-in
per market, and left the newest 20% holdout sealed.

| Sizing | Trades | Skipped | Mean target | Net P&L | 2-cent stress | Max drawdown | Positive stressed blocks |
|---|---:|---:|---:|---:|---:|---:|---:|
| Fixed $1 | 838 | 0 | $1.00 | +$29.6609 | +$12.1890 | $5.1635 | 3/5 |
| 1/32 Kelly | 0 | 838 | n/a | $0.0000 | $0.0000 | $0.0000 | 0/5 |
| 1/16 Kelly | 216 | 622 | $0.9447 | -$0.4644 | -$4.6219 | $6.2299 | 2/5 |
| 1/8 Kelly | 838 | 0 | $1.3946 | +$27.8864 | +$3.8363 | $9.6854 | 2/5 |
| 1/4 Kelly | 838 | 0 | $2.5956 | +$62.5837 | +$9.5694 | $26.7625 | 3/5 |
| 1/2 Kelly | 838 | 0 | $2.9959 | +$106.6278 | +$41.7829 | $27.0156 | 3/5 |

Fixed $1 is the descriptive risk-adjusted leader. Its two-cent-stressed P&L divided by drawdown is 2.36, versus
0.40 for eighth Kelly, 0.36 for quarter Kelly and 1.55 for half Kelly. It also has the lowest active-path
drawdown. The half-Kelly headline is mostly the $3 cap: it reached the cap on 829 of 838 decisions, so its
+$106.6278 result represents roughly triple-sized exposure and a $27.0156 historical drawdown rather than a
useful probability-sensitive sizing improvement.

Small Kelly fractions did not solve the risk problem. One-thirty-second Kelly could not afford one contract on
any decision. One-sixteenth Kelly selected only 216 decisions and lost money despite a 76.39% win rate, showing
that win rate alone did not cover price and fee economics. Eighth Kelly retained every decision but produced less
base P&L than fixed $1, only +$3.8363 under two-cent stress, and almost doubled drawdown.

The sizing result does not repair Study 023's failed strategy gate. Fixed $1 still lost under two-cent stress in
two of five chronological blocks and its validation drawdown exceeded the preregistered $5 cap. Because Kelly
uses the model probability as truth, any remaining calibration error magnifies position size in exactly the
periods where the model can be wrong. No Kelly variant, holdout opening, demo run or live execution is authorized
by this study.
