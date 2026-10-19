# Market-Shrunk Fallback Validation 023 Result

Study 023 completed its one frozen validation evaluation on 2026-10-18 and was rejected. Registration SHA-256:
`c495c50f272944978906dcaaabf29fe2889e4dd47c449c9e229612af8f8e4307`. Machine-report SHA-256:
`f88306796a1206d8da0a0592911746477b3fadfecfc2dc2bc86374fa92e8ee81`. The development replay reproduced the
Study 022 trade ledger exactly.

## Results

| Metric | Development | Validation | Combined 80% |
|---|---:|---:|---:|
| Observed UTC days | 110 | 37 | 147 |
| Trades | 586 | 252 | 838 |
| Trades/day | 5.33 | 6.81 | 5.70 |
| Win rate | 71.16% | 70.63% | 71.00% |
| Mean entry price | 66.34 cents | 66.68 cents | 66.44 cents |
| Net P&L | +$22.2369 | +$7.4240 | +$29.6609 |
| P&L without three largest wins | +$19.0410 | +$4.2683 | +$26.4650 |
| One-cent adverse-price P&L | +$16.0739 | +$4.8450 | +$20.9189 |
| Two-cent adverse-price P&L | +$9.9209 | +$2.2681 | +$12.1890 |
| Maximum drawdown | $4.4504 | $5.1635 | $5.1635 |
| Positive-day share | 57.27% | 54.05% | 56.46% |

Validation passed frequency, win rate, mean price, base P&L, ex-top-three P&L, one- and two-cent stress, positive-day
share and three-of-five base and stressed block gates. It missed the frozen $5 drawdown cap by $0.1635.

Combined results exceeded Study 020's near miss on base P&L, ex-top-three P&L and two-cent stress, passed four of
five base blocks, stayed below $10 drawdown and retained a positive one-sided 90% daily-mean lower bound. Combined
two-cent-stressed blocks were `+$6.9776`, `+$3.2067`, `-$2.4167`, `+$5.0960`, and `-$0.6746`, so only three of five
were positive. That failed the frozen four-of-five stressed-consistency gate.

## Decision

Study 023 is rejected under its preregistered gate. Risk sizing remains closed because larger bets cannot repair
the two negative stressed periods. The result is the strongest historical lead found in Studies 019–023, but it
averages 5.70 rather than roughly ten trades per day and is not stable enough for live orders.

The exact signal is suitable for a read-only executable-book forward shadow study if more evidence is desired.
Such a study must keep the parameters frozen, observe actual 500 ms arrival quotes and depth, and require new
chronological evidence. It is not authorized for demo or real-money orders, and the final Dataset 017 holdout
remains sealed.
