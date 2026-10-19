# Market-Shrunk Fallback Validation 023

Declared on 2026-10-18 before opening the Study 022 validation partition. This one-configuration, read-only check
does not evaluate Dataset 017's final 20% holdout and cannot place an order.

Study 022 found no robust 8–12-trade/day signal. Its one configuration that passed every other development gate
averaged 5.33 trades/day. Study 023 freezes that exact configuration: 90% fast variance weight, 25% Kalshi
log-odds weight, neutral drift, no quote confirmation, 0.5% edge floor, 45–80 cent entry band, 7.5-point maximum
raw-model/market gap, 5–300 seconds left, two-cent spread, nonnegative two-cent-stressed modeled edge and no
variance-ratio filter.

The development replay must reproduce trade-ledger SHA-256
`7d86eba8d136a45129974695ca1f00a14173ed233e9ec1f6b881539a2ec34db1`. The next 20% validation partition is then
evaluated exactly once. It must average 4–7 trades per observed day, win at least 65%, enter at 45–72 cents on
average, remain positive under base, ex-top-three, one-cent and two-cent P&L, win on a majority of days, pass three
of five base and stressed chronological blocks, and draw down no more than $5.

The combined 80% must retain 4–7 trades/day, exceed Study 020's near miss on base, ex-top-three and two-cent-
stressed P&L, pass four of five base and stressed blocks, draw down no more than $10 and have a positive one-sided
90% lower bound for mean daily P&L. Risk sizing opens only after all fixed-$1 validation and aggregate gates pass.

This explicitly tests a lower-frequency fallback. It cannot be described as meeting the original roughly-ten-
trades-per-day objective, and a pass still requires the untouched holdout and executable-book forward validation.
