# Risk sizing audit 001 protocol

Declared on October 3, 2026 after Railway deployment
`0d516a76-d7e8-43f3-b11b-adadc7329b2f` began recording sizing plans and before the first eligible sizing
observation settled. At declaration, protected status contained two production audit snapshots, zero settled
sizing signals and one new demo fill awaiting settlement.

## Objective

Compare fixed and fractional-Kelly risk sizing on the same future adaptive-volatility signals without
changing the active strategy or its $3 demo order cap. This audit measures sizing conditional on a signal;
it cannot establish that the underlying strategy has an edge.

## Frozen variants

All variants use a $100 reference bankroll, modeled Kalshi fees, integer contracts and a hard $3 maximum
modeled cost per market.

1. `fixed_1`: spend up to $1.
2. `fixed_3`: spend up to $3; this is the current demo cap.
3. `eighth_kelly_cap_3`: one-eighth of full Kelly, capped at $3.
4. `quarter_kelly_cap_3`: one-quarter of full Kelly, capped at $3.
5. `half_kelly_cap_3`: one-half of full Kelly, capped at $3.

Kelly probabilities use the frozen Candidate Study 003 symmetric temperature calibration. Full Kelly is
computed from the calibrated selected-side probability and the all-in one-contract cost. A non-positive
Kelly edge produces a zero-contract recommendation.

## Eligible observations

An observation must be recorded after the deployment above, use the production quote captured at the
500 ms arrival target, pass the production strategy's freshness, fee, market-status and four-percentage-point
edge checks, and later receive an official market result. A proposed position is executable only when the
recorded best-level production depth covers its integer contract count. Missing, late, stale or shallow
observations remain visible and are not converted into favorable fills. Earlier demo trades are excluded
because their exact production arrival quotes were not recorded.

## Review gate

Do not select a sizing method before both conditions hold:

- at least 20 distinct UTC dates containing post-declaration observations;
- at least 50 production-qualified, officially settled observations with enough depth for `fixed_3`.

If Candidate Study 003 fails its own promotion gate, this sizing audit cannot promote any Kelly method.
If the sizing audit is still below 50 common-depth observations at Candidate Study 003's 20-day review,
report it as incomplete and continue collecting without changing parameters.

## Evaluation

The primary comparison uses the common cohort with enough displayed depth for the largest proposed size.
A zero Kelly size remains in that cohort as a deliberate no-trade with zero P&L. Report, for every variant:

- net P&L after modeled fees;
- P&L after removing the three largest winners;
- maximum sequential drawdown from the $100 reference bankroll;
- positive UTC-day percentage;
- number of zero-size decisions and depth failures;
- results after adding one cent and two cents of adverse fill price, where a contract remains valid.

A variant must have positive net P&L, remain positive after removing its three largest winners, remain
positive under one-cent adverse fills, be positive on more than half of observed UTC dates, and keep maximum
drawdown at or below $15. Among variants that pass, prefer the smallest Kelly fraction unless a larger one
improves return without increasing maximum drawdown or top-winner dependence. Half Kelly is not the default.

Passing this audit permits an untouched validation study. It does not authorize production orders or an
automatic change to demo sizing.
