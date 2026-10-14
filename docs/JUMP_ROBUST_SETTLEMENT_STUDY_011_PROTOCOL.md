# Jump-Robust Settlement Study 011 development protocol

Declared on 2026-10-13 before implementing the full forecast or calculating Study 011 P&L. This study shares the
read-only fixed-offset decision tape defined for Study 010 and has no order-submission path.

## Question

Can a parsimonious realized-volatility model improve probability calibration and executable returns relative to
both the failed adaptive Gaussian forecast and the contemporaneous Kalshi midpoint?

## Frozen features

At each registered decision, use only contiguous one-second BRTI prices already received. For windows of 60, 300
and 1,800 seconds calculate realized variance, bipower variation, positive and negative realized semivariance,
jump variation and jump share:

```text
RV_h  = sum r_i^2
BPV_h = (pi/2) sum |r_i||r_(i-1)|
J_h   = max(RV_h - BPV_h, 0)
RS+_h = sum r_i^2 1[r_i > 0]
RS-_h = sum r_i^2 1[r_i < 0].
```

A missing second in the 1,800-second history makes the Study 011 forecast unavailable. Already observed seconds
of the official settlement window remain exact inputs.

## Frozen model comparison

Fit only prior officially settled UTC dates and compare:

1. existing adaptive Gaussian probability;
2. ridge HAR using log realized variance at 60, 300 and 1,800 seconds;
3. the same HAR plus jump share and signed-semivariance imbalance.

Use Student-t standardized residuals for remaining-path simulation, not a normal tail. Simulated paths must insert
known settlement seconds, produce the exact 60-second arithmetic average and apply the contract's cent rounding.
Model selection uses prequential log loss against the official result before any strategy P&L comparison.

The first implementation milestone is the causal, gap-sensitive shared decision tape and frozen feature audit.
The HAR fit, residual distribution and path simulator require a separate source-hash freeze before P&L is opened.

## Falsification

Reject the complex model if it does not beat both the adaptive forecast and Kalshi midpoint on later-date log loss
and Brier score, or if any apparent P&L fails the two-cent stress, top-three-winner removal, daily consistency or
chronological-block gates. A better volatility forecast alone is not a trading edge.
