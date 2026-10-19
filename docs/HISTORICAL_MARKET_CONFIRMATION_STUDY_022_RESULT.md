# Historical Market Confirmation Study 022 Result

Study 022 completed its preregistered 11,664-cell development grid on 2026-10-18. No configuration passed every
development gate, so validation, risk sizing and the final holdout remained closed. Registration SHA-256:
`6b51e3a4bb3dd07ad75a15b46e0836f997af18ff4778258f3861a46dd65e3996`. Machine-report SHA-256:
`4a6d82994fef8310e05f41152236d44b70ec2c4b652cd10c6a0ba60eb4c5fd2c`.

Among 327 cells averaging 8–12 trades per day, 270 also met the 65% win-rate and 45–72-cent mean-price targets,
216 made positive base P&L, and none remained positive under a two-cent adverse fill. The best stressed result in
that target band averaged 8.95 trades/day, won 70.02%, entered at 66.56 cents, made $19.9002 before stress and lost
$0.5970 under two-cent stress. It drew down $11.5260 and was positive in only three of five base and stressed
blocks. The cell closest to exactly ten trades/day made only $2.1464, lost $21.1564 under two-cent stress and drew
down $27.0840.

Stronger quote confirmation did not solve the frequency requirement. The best nonnegative selected-side quote
confirmation averaged 0.88 trades/day. The best one-cent confirmation averaged 0.39 trades/day. Both were
profitable and stressed-positive in development, but too sparse and dependent on far fewer active days.

The useful lead was an unconfirmed, market-shrunk fallback that failed only the requested 8-trade minimum:

| Metric | Development result |
|---|---:|
| Trades | 586 |
| Trades per observed day | 5.33 |
| Win rate | 71.16% |
| Mean entry price | 66.34 cents |
| Net P&L | +$22.2369 |
| P&L without three largest winners | +$19.0410 |
| Two-cent adverse-price P&L | +$9.9209 |
| Positive-day share | 57.27% |
| Positive base blocks | 4 of 5 |
| Positive two-cent-stressed blocks | 4 of 5 |
| Maximum drawdown | $4.4504 |
| One-sided 90% daily-mean lower bound | +$0.0164/day |

Its frozen parameters are 90% fast variance weight, 25% Kalshi midpoint weight in log-odds space, no quote
confirmation, 0.5% net-edge floor, 45–80 cent entry band, 7.5-point maximum raw-model/market gap, 5–300 seconds
left, two-cent spread limit, nonnegative two-cent-stressed modeled edge, and no variance-ratio filter.

Study 022 is rejected for the 8–12-trade objective. The 5.33-trade lead may receive one separately preregistered
validation evaluation with its parameters unchanged. That would test a lower-frequency fallback; it cannot be
reported as satisfying the original ten-trade goal.
