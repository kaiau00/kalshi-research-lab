# Market-Shrunk Regime Failure Analysis 025

Study 025 is a read-only diagnostic of the exact 838 fixed-$1 decisions selected by Study 023. It asks why the
signal lost under two-cent adverse-price stress in two of five chronological blocks even though aggregate P&L,
validation P&L and aggregate stress were positive. It does not change the signal, search a new parameter grid,
select a production filter, evaluate the final holdout or submit an order.

The source is Dataset 017's already-viewed oldest 80%. The newest 20% remains sealed. The replay must reproduce
Study 023's fixed-$1 trade-ledger SHA-256
`149f874d7e98af5b4720b0b1ee7a489d8e05b7330db93bf45f74e7c9fae37773` before reporting anything.

## Frozen diagnostic views

The study reports development and validation separately for side, selected entry price, seconds remaining,
absolute raw-model versus Kalshi gap, modeled net edge, fast/slow variance ratio, selected-side Kalshi
probability, UTC hour and chronological block. Each bucket reports trades, wins, a Wilson 90% win-rate interval,
fees, base P&L, P&L without its three largest winners, one- and two-cent adverse-price P&L, drawdown and winner
concentration.

A bucket is called a repeatable weakness only when it has at least 20 trades in each partition and negative
two-cent-stressed P&L in both. A repeatable strength uses the same count rule and requires positive stressed P&L
in both. Opposite signs are labeled partition instability. These labels are diagnostic evidence, not candidate
selection rules.

## Decision rule

Study 025 cannot promote, modify or stop the live strategy. Any proposed filter must be justified after reviewing
this report, frozen as a separate candidate, and evaluated without tuning on the sealed holdout. Production rules
and sizing remain unchanged.
