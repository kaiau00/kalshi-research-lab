# Market Anchor Study 005 interim results

**Decision: start prospective collection; do not trade it live.** The frozen filter was positive in both the
exploratory development window and the later secondary window, including after removing the three largest
winners and under two cents of adverse fills. The secondary window was positive in only three of five
chronological blocks, and neither window has the required 20 prospective UTC dates.

| Window | Dates | Settlements | Net P&L | Without top 3 | 1¢ stress | 2¢ stress | Positive days | Blocks | Drawdown |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Study 004 development | 10 | 277 | +$13.6701 | +$7.5333 | +$10.5032 | +$7.3424 | 8/10 | 4/5 | $6.9332 |
| Study 003 secondary | 10 | 294 | +$8.1592 | +$4.1707 | +$4.9173 | +$1.6809 | 6/10 | 3/5 | $5.3735 |

The candidate keeps the original adaptive 4% signal and accepts it only when the selected-side decision quote
is at least $0.30 and below $0.95, the raw model and Kalshi midpoint differ by no more than eight percentage
points, and the binary spread is at most two cents. All filters use information available before the simulated
order.

The Study 004 result is data-mined and the Study 003 aggregate performance had already been viewed before this
filter was designed. Both are therefore supporting evidence rather than proof. The prospective window begins
at 2026-10-10 00:00:00 UTC and must reach 20 observed UTC dates and 100 official settlements while passing every
frozen robustness gate. A pass permits another confirmation study and does not authorize production orders.

Machine-readable evidence is preserved in
[`market-anchor-study-005-development.json`](validation/market-anchor-study-005-development.json) and
[`market-anchor-study-005-secondary.json`](validation/market-anchor-study-005-secondary.json).

