# Market Anchor Study 005 protocol

Study 005 investigates one deliberately simple filter for the existing adaptive-volatility signal. It does
not change Candidate Study 003, authorize an order, or use production execution. The purpose is to test
whether the original model has value only when the Kalshi market substantially agrees with it and the quote
is outside the extreme tails.

## Frozen development source

- Dataset `e2d5cb33e7c44660809b531f03d4b4e3`, Study 004 segments 0–4344
- Ten UTC dates, September 21–30, 2026
- Baseline account `signal_raw_e04`: adaptive volatility, 4% minimum modeled net edge, 5–300 seconds
  remaining, $1 maximum modeled cost, 500 ms delayed IOC, recorded fees, and official outcomes

Study 004's ordinary strategy grid found no winner. This new analysis inspected additional decision-time
features and therefore is exploratory and multiple-tested. Its development result cannot establish an edge.

## Frozen candidate

`market_agreement_band_001` inherits every baseline signal and execution rule, then requires all of the
following information available at the original decision time:

- selected-side best ask at least $0.30 and strictly below $0.95;
- absolute difference between the raw model YES probability and the Kalshi two-sided midpoint no greater
  than 8 percentage points; and
- binary spread no greater than $0.02.

The rule uses the decision-time limit quote, never the later fill price. It does not fit a machine-learning
model, use settlement outcomes at decision time, change sizing, or add exits.

## Review sequence

1. Record the complete development result from Study 004.
2. Apply the frozen filter once to Candidate Study 003's existing baseline fills as a secondary retrospective
   validation. Study 003 aggregate results were already visible, so this is informative but not untouched.
3. Regardless of the secondary result, start a new prospective observation window after the registration
   and source code are frozen. Only that future window can satisfy the formal gate.

The prospective window is frozen to begin at **2026-10-10 00:00:00 UTC**. It filters only new simulated
`adaptive_baseline` fills created at or after that instant from Candidate Study 003. The protected
`/api/market-anchor/status` report reads the existing verified checkpoint, so this adds no second raw-event
replay and no trading path.

Formal review requires at least 20 prospective UTC dates and 100 official settlements. Net P&L, P&L after
removing the three largest winners, one-cent and two-cent adverse-fill P&L, more than 50% positive days,
at least four positive chronological blocks out of five, and maximum drawdown no greater than $20 must all
pass. A passing result permits another untouched confirmation; it does not authorize live trading.
