# Historical Frequency Strategy Study 021

Declared on 2026-10-18 before calculating any Study 021 P&L. This is read-only, development-only research. It
cannot place demo or production orders and does not open Dataset 017's newest 20% holdout.

## Question

Can a strategy average 8–12 fixed-$1 trades per observed UTC day, win at least 65% of them, maintain a mean entry
price from 45 to 72 cents, and still produce robust positive expectancy after fees and adverse-price stress? Win
rate is not an objective by itself: expensive favorites can win often and lose money overall.

## Frozen search

The 11,520-cell grid combines three fast/slow variance weights, zero or 10% Kalshi-midpoint pooling, four forecast
families, four net-edge floors, five selected-ask bands, three raw-model/market gap limits, two entry windows, one-
or two-cent spread limits, and either no volatility-regime filter or a 1.5 maximum fast/slow variance ratio.

The four forecast families apply -0.25, zero, +0.25 or +0.50 times the trailing 60-second log-return drift to every
unobserved second in the exact final-minute settlement average. They respectively test mean reversion, the prior
zero-drift model, mild momentum and stronger momentum. The same frozen Gaussian covariance calculation converts
each projected average to a crossing probability.

Each market contributes at most its first qualifying completed-minute decision. Entry fees are included. Every
cell must also have nonnegative modeled edge after adding two cents to the entry price and charging the fee.

## Selection and validation

Only the oldest 60% development partition selects the configuration. It must average 8–12 trades per day, win at
least 65%, have a 45–72 cent mean entry, make more than $15 fixed-$1 P&L and more than $10 after removing its three
largest wins, remain positive under one- and two-cent stress, be profitable on a majority of days and in four of
five chronological blocks under both base and two-cent prices, keep drawdown at or below $10, and have a positive
one-sided 90% lower bound for mean daily P&L.

The single selected configuration is then frozen and scored on the next 20% validation partition. Validation must
retain the same frequency, win-rate and mean-price ranges; positive base, ex-top-three, one-cent and two-cent P&L;
positive P&L on a majority of days and three of five base and stressed blocks; and drawdown no greater than $5.

Across development plus validation, a promotion candidate must exceed Study 020's near miss on base P&L
($24.4806), ex-top-three P&L ($21.2847) and two-cent-stressed P&L ($9.2233), pass four of five aggregate base and
stressed blocks, keep drawdown at or below $10 and retain a positive one-sided 90% daily-mean lower bound.

Risk variants remain closed unless all three gate sets pass under fixed $1. If they open, the already registered
fixed $1, $1.50, $2 and $3 and one-sixteenth- and one-eighth-Kelly-with-$3-cap paths use identical decisions.

The validation slice has been viewed by prior studies, so even a complete pass remains a research candidate. It
must survive the still-sealed holdout once and then a separately frozen executable-book forward study.
