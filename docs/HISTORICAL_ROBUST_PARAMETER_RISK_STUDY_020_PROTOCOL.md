# Historical Robust Parameter and Risk Study 020

Declared on 2026-10-18 before calculating any Study 020 P&L. This is development-only, read-only research. It
has no demo or production order path, and it does not open Dataset 017's newest 20% holdout.

## Reason for the study

Study 019's selected fixed-$1 signal made $11.9751 across 549 trades, but only two of 1,620 searched cells passed,
its daily confidence interval included zero and its original-validation slice lost $0.3789 under two cents of
adverse price. Study 020 tests whether a meaningfully stronger neighboring signal exists. It must beat the Study
019 lead at fixed $1 before any risk comparison can matter.

## Frozen development search

Use only the already-viewed first 80% of Dataset 017 with the same source checksums, exclusions, causal benchmark
clock, completed-minute quote clock, fee model and first-qualifying-decision rule as Studies 018 and 019. Search
4,608 fixed combinations of:

- 50%, 70% or 90% weight on 60-second variance, with the balance on 600-second variance;
- zero or 10% interpolation toward Kalshi's midpoint in log-odds space;
- 2%, 2.5%, 3% or 3.5% minimum modeled net edge;
- eight selected-side ask bands from $0.45-$0.80 through $0.60-$0.90;
- 5%, 6% or 7.5% maximum raw-model-versus-market gap;
- entry windows of 5-180, 5-300, 30-180 or 30-300 seconds before close;
- one- or two-cent binary spread ceilings; and
- nonnegative edge after adding two cents and the one-contract fee.

Signal selection always uses a $100 starting balance and fixed $1 maximum all-in cost. A candidate must exceed the
Study 019 lead's base P&L, P&L without its three largest winners and two-cent-stressed P&L. It must also have at
least 200 settlements, positive one-cent stress, more than half of all research dates positive, four of five
positive base blocks, four of five positive two-cent-stressed blocks, at most $10 drawdown and a positive
one-sided 90% lower confidence bound for mean daily P&L. The original development and validation partitions must
each remain positive in base P&L, P&L without their own three largest winners and two-cent stress; validation must
contain at least 75 settlements.

Rank only complete gate passers. The frozen order is worst two-cent-stressed block P&L, original-validation
two-cent-stressed P&L, aggregate two-cent-stressed P&L, P&L without the three largest winners, lower drawdown and
lexical name. If no cell passes, Study 020 has no winner and the holdout remains sealed.

## Frozen risk comparison

Only the selected fixed-$1 signal, if one exists, receives the separate $100-bankroll risk comparison. Compare
fixed $1, $1.50, $2 and $3 maximum all-in cost with one-sixteenth and one-eighth Kelly capped at $3. Kelly uses
the current balance, integer contracts and fees inside its target. One- and two-cent stress preserve the base
quantity.

Risk cannot promote a failed signal. A risk variant is recommendable only if it remains positive after removing
its three largest winners and under two-cent stress while keeping maximum drawdown at or below $10. Rank eligible
variants by two-cent-stressed P&L divided by drawdown, then stressed P&L, lower drawdown and lower average budget.
This research recommendation cannot authorize a live risk change.

Minute candles do not prove displayed depth or a 500 ms IOC fill. Any surviving candidate still requires the one
untouched holdout evaluation and then forward executable-book validation.
