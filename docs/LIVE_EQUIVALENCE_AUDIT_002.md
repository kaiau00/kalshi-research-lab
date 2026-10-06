# Live-equivalence audit 002

**Decision: the adaptive-volatility demo P&L did not transfer to the production order book.** The demo
account remains useful for validating order handling, but its headline return is not a forecast of live-account
profitability.

## Scope

This audit uses 152 settled adaptive-volatility demo fills from October 3–6 for which the service captured the
real Kalshi production order book at the modeled 500 ms arrival time. It tests the same side with the frozen 4%
edge requirement, production fee support, current production quote, displayed depth, and the unchanged $3
maximum risk. It places no production orders.

The median snapshot timing error was 0.82 ms and the 95th percentile was 96.01 ms. Two captures were more
than 500 ms late. Excluding all captures more than 250 ms from the target changes production-equivalent P&L
from -$2.1620 to -$2.3752 and does not change the decision.

## Result

| Check | Result |
|---|---:|
| Settled demo fills with exact production capture | 152 |
| Demo P&L on all 152 | +$74.1665 |
| Production-transferable fills | 41 (26.97%) |
| Demo P&L on those same 41 | -$1.6325 |
| Production-equivalent P&L at displayed quotes | **-$2.1620** |
| Production-equivalent P&L at one cent worse | **-$4.5052** |
| Production-equivalent P&L at two cents worse | **-$6.8328** |
| Production-equivalent maximum drawdown | $17.6133 |
| Production P&L excluding its three largest winners | **-$21.9106** |

Of the other 111 demo fills, 106 did not meet the 4% edge requirement in the production book, one lacked
enough displayed production depth, three lacked matching production terms at capture, and one lacked a valid
production book. The positive demo result therefore came mainly from prices that were not available as
qualifying opportunities in production.

The transferable subset reached the same directional outcomes in demo and production: 27 wins and 14 losses.
Its P&L was negative in both environments. The production result was worse because contract quantities, fees,
and available prices differed. Its three largest winners supplied 53.36% of all positive P&L; removing them
turns the result deeply negative.

## Limits

Displayed production depth can disappear before a real order arrives, so even this audit is more favorable than
confirmed live fills. It evaluates whether the demo-selected trades transfer to production; it does not invent
signals that appeared only in production. Candidate Study 003 separately evaluates the strategy directly on
the production feed and still must pass its preregistered 20-day robustness gates.

The frozen machine-readable result is in
[`validation/live-equivalence-audit-002.json`](validation/live-equivalence-audit-002.json). Reproduce it with:

```shell
PYTHONPATH=src python scripts/audit_live_equivalence.py \
  --db /data/demo-adaptive-volatility-001/orders.sqlite3
```
