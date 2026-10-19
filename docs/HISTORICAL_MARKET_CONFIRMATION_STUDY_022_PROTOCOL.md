# Historical Market Confirmation Study 022

Declared on 2026-10-18 before calculating any Study 022 P&L. This read-only development study cannot submit an
order and leaves Dataset 017's newest 20% holdout sealed.

Study 021 found that the structural model could generate the requested frequency, win rate and average price, but
nearly all high-frequency cells failed a two-cent adverse-price test and the sole survivor had a $17.72 drawdown.
Study 022 changes the information rule rather than searching smaller threshold steps.

The 11,664-cell grid uses 15%, 25% or 35% Kalshi-midpoint weight in a log-odds probability pool. It also compares
no quote filter, confirmation that the selected side's midpoint probability did not fall since the previous
completed minute, and confirmation that it rose by at least one cent. The remaining frozen axes cover variance
weight, edge, price band, model/market gap, timing, spread, additional stressed-edge margin and a volatility-ratio
filter.

The oldest 60% partition alone selects the configuration. The fixed-$1 development, validation and aggregate gates
are exactly those preregistered for Study 021: 8–12 trades per observed UTC day, at least 65% wins, 45–72 cent mean
entry, positive concentration and one-/two-cent stress tests, chronological consistency, bounded drawdown and
positive daily uncertainty. The aggregate result must exceed Study 020's near miss. Risk variants open only after
every fixed-$1 gate passes.

The next 20% validation partition has been viewed by prior studies and is therefore only a diagnostic. A passing
result still needs the one untouched final holdout evaluation and a separate executable-book forward test.
