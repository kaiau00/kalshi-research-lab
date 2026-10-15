# Historical Parameter and Kelly Study 019

Declared on 2026-10-15 before calculating any Study 019 grid or Kelly P&L. This is read-only research and has no
demo or production order path.

## Source and isolation

Use the already-viewed first 80% of Dataset 017 that Study 018 assigned to development and validation. Treat all
of that interval as research data because its results are now known. Keep Study 018's newest 20%, containing 3,463
markets, sealed. Apply the same fixed source-audit exclusions and causal clock as Study 018.

## Fixed signal grid

All 1,620 configurations use the adaptive forecast with its existing 70% weight on 60-second variance and 30%
weight on 600-second variance. Test raw probability and 25% or 50% interpolation toward Kalshi's midpoint in
log-odds space. Cross these probability choices with:

- minimum net edge of 3%, 4% or 5%;
- selected-side ask bands of $0.30–$0.70, $0.30–$0.85, $0.40–$0.75, $0.40–$0.80 or $0.50–$0.85;
- maximum absolute raw-model-versus-market gap of 3%, 4.5% or 6%;
- entry no earlier than 120, 180 or 300 seconds before close;
- maximum binary spread of one or two cents; and
- minimum selected-side edge after a two-cent adverse price of 0% or 2%.

The first qualifying completed minute candle consumes the market. Base entry uses its selected-side closing ask,
the frozen quadratic taker fee and official settlement. Quotes have no depth or 500 ms arrival path and therefore
cannot establish executable fills.

## Signal selection

Use an independent $100 starting bankroll and fixed $1 maximum all-in cost for primary parameter selection. Do
not use cooldowns, daily stops or a realized-drawdown halt in this screen; those can truncate a bad sequence but
cannot prove an entry edge. Assign the complete research-market chronology to five fixed contiguous time blocks.

A configuration advances only with at least 100 settlements; positive base P&L; positive P&L after removing its
three largest winners; positive one- and two-cent adverse-price P&L; more than half of all observed UTC dates
positive; at least four of five market-time blocks positive; and maximum drawdown no greater than $10. Rank only
gate passers by minimum block P&L, P&L without the three largest winners, two-cent stress, lower drawdown, sample
size and lexical name. If none passes, the study has no signal winner and the holdout remains sealed.

## Frozen sizing comparison

For the same signal decisions, start each sizing path with $100 and compare:

1. fixed $1 maximum all-in cost;
2. fixed $3 maximum all-in cost;
3. one-eighth Kelly capped at $3;
4. one-quarter Kelly capped at $3; and
5. one-half Kelly capped at $3.

For selected probability `p` and one-contract all-in cost `c`, full Kelly is:

```text
f* = max(0, (p - c) / (1 - c))
```

Fractional Kelly's target budget is the current cash balance times `f*` times its multiplier, capped at $3. Use
integer contracts with fees inside the target budget. A target too small for one contract is a recorded zero-size
decision. One- and two-cent stress preserve the base quantity rather than favorably resizing after seeing the
worse price.

Sizing cannot promote a signal that fails the fixed-$1 gate. Report net P&L, top-three-winner concentration,
stress, drawdown, ending cash, zero-size decisions, and ruin or inability to afford another contract for every
variant. Kelly results are sizing diagnostics, not evidence that Kelly creates an edge.

The machine-readable registration in `src/historical_optimization/registration.py` is authoritative.
