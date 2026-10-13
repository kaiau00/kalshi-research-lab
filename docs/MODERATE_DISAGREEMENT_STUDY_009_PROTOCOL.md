# Moderate Disagreement Study 009

Declared on October 13, 2026 before the prospective cutoff at 2026-10-13 21:45:00 UTC. This is a read-only,
signal-only study. It cannot submit an order, change the paused production runner, or promote itself.

## Why this candidate exists

Study 008 showed that Kalshi's midpoint was better calibrated than the raw adaptive model in aggregate. A
post-result diagnostic of the same development checkpoint found one simpler regime where the exact recorded
economics remained positive: moderately priced contracts with moderate model-versus-market disagreement. That
diagnostic is hypothesis generation, not validation, because its data has already been inspected.

The single frozen candidate is `moderate_disagreement_band_001`. It may only accept or reject the side already
selected by the unchanged `adaptive_baseline` account in Candidate Study 003. It cannot infer an opposite-side
fill.

## Frozen entry rules

- KXBTC15M only, exchange index 2, subaccount-independent research simulation
- unchanged adaptive-volatility source signal with 4% minimum modeled net edge
- unchanged 5–300 second entry window and 500 ms delayed IOC fill observation
- selected-side decision ask from $0.30 inclusive to $0.50 exclusive
- absolute raw-model-versus-Kalshi midpoint gap greater than 0.06 and at most 0.08
- binary spread at most $0.01
- nonnegative raw selected-side edge after adding $0.02 to the decision ask and applying the one-contract fee
- recorded delayed fill and displayed-depth-capped quantity, with $1 maximum all-in simulated cost
- one-hour cooldown after a fill
- UTC-day halt at realized P&L at or below -$2 or after three consecutive settled losses
- indefinite halt at $5 maximum realized drawdown
- hold to official settlement; no early exit

## Frozen review

Review begins only after at least 20 prospective UTC dates and 50 officially settled selections. Report exact
fees, net P&L, P&L without the three largest winners, one- and two-cent adverse-fill stress, positive-day share,
five chronological blocks, maximum drawdown, Brier score, binary log loss, unresolved exposure and every gate.

Every gate must pass: positive net P&L; positive P&L without the three largest winners; positive one- and two-cent
stress; positive results on more than half of observed UTC dates and in at least four of five blocks; maximum
drawdown at most $5; and selected-side Brier score and binary log loss no worse than the contemporaneous Kalshi
midpoint. Reaching the sample counts or passing this review cannot authorize real-money trading. A later demo
execution phase must reproduce at least 50 exchange-reported fills under a separately frozen registration before
any live proposal.

## Development disclosure

The post-result development slice selected 45 trades, produced +$5.8736 net P&L, +$1.1587 without its three
largest winners, +$4.9689 and +$4.0657 under one- and two-cent stress, 64.3% positive days, four positive blocks,
and $3.8361 maximum drawdown. The raw selected-side probability also beat the Kalshi midpoint on Brier score and
log loss within that selected slice. These figures chose the rule and therefore provide no untouched evidence.
