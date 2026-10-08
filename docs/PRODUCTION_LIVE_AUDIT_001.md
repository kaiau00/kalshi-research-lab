# Production live audit 001

New real-money entries were paused on October 8, 2026. Recording, Candidate Study 003, archival, account
verification, and official-settlement reconciliation remain active. All 37 production fills were officially
resolved before this review. The account had $62.9380 cash and -$37.0860 realized net P&L from its $100 baseline.

## Result by production phase

| Phase | Trades | Wins | Actual net P&L | Hold-to-settlement P&L | Exit advantage |
|---|---:|---:|---:|---:|---:|
| Original $3 hold phase | 23 | 12 | -$24.2438 | -$24.2438 | $0.0000 |
| $3 monitored-exit phase | 8 | 5 | -$3.4328 | +$8.5782 | -$12.0110 |
| $2 hold phase | 6 | 0 | -$9.4094 | -$9.4094 | $0.0000 |
| **All production fills** | **37** | **17** | **-$37.0860** | **-$25.0750** | **-$12.0110** |

The lower $2 cap limited the amount committed to each new trade, but it did not improve the signal. The six trades
after that revision all lost. Their probabilities implied 1.32 expected wins, but a zero-win run still had about a
14% probability under the model, so that phase alone is too small to diagnose the strategy.

## What the complete record shows

The stronger evidence is the full record. The model assigned an average 60.9% probability to the selected side
and expected 22.54 wins. Only 17 won, a 46.0% win rate and a calibration gap of -15.0 percentage points. Based on
the recorded probabilities and actual filled quantities, the model expected +$24.7023 from holding every entry.
The identical-entry hold result was -$25.0750, a -$49.7773 gap from the model expectation.

If all 37 outcomes were independent Bernoulli trials at their recorded probabilities, the chance of 17 or fewer
wins would be 0.85%, and the chance of a hold payout this low or lower would be 3.60%. Adjacent BTC 15-minute
markets are correlated, so these are diagnostics rather than final statistical p-values. They still reinforce the
practical conclusion that the production probabilities were too confident for the observed outcomes.

The monitored exits made the result worse. Those eight entries would have earned +$8.5782 if held to settlement.
The exits produced -$3.4328, reducing P&L by $12.0110. Keeping early exits disabled is supported by the completed
counterfactual evidence.

No simple filter is supported by these 37 trades:

- YES selections lost $10.3026 on a hold basis; NO selections lost $14.7724.
- Entry prices below 10 cents, 10–19 cents, 20–39 cents, and at least 40 cents all lost on a hold basis.
- Modeled edges of 4–4.99%, 5–7.49%, and at least 7.5% all lost on a hold basis. Raising only the edge threshold is
  not supported by this sample.
- Thirty-four trades arrived with 180–300 seconds left and lost $23.3931 on a hold basis. Only three arrived later,
  which is too little evidence to claim a better timing window.

## Decision

The current adaptive-volatility strategy has not demonstrated a live edge and should remain paused. Retuning a
price, edge, side, or timing filter on these same 37 trades would be in-sample selection and would not establish a
new edge. The next candidate should address probability calibration or the return-distribution model, be frozen
before evaluation, and pass the existing forward-study gates before any request to resume real-money entries.

The machine-readable evidence is in
[`validation/production-live-audit-001.json`](validation/production-live-audit-001.json). The report contains no
API credentials, account identifiers, order identifiers, or private keys.
