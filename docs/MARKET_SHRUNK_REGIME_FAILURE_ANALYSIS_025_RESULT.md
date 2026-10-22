# Market-Shrunk Regime Failure Analysis 025 Result

Study 025 completed its read-only diagnostic on 2026-10-21. Registration SHA-256:
`d2e224451786f24d24d1f4a6045de0d9705b8c69897ed4e41d317654bd561a94`. Machine-report SHA-256:
`9cd054f0f63b1fc66c93387f51964a81ef5726068644626f55f20b45680610ba`. The replay reproduced Study 023's
fixed-$1 trade-ledger SHA-256 exactly. The newest 20% holdout was not evaluated.

## What repeated

The exact Study 023 signal selected 838 trades over 147 UTC dates. It made $29.6609 at fixed $1 sizing and
$12.1890 after repricing every selected trade two cents adversely. Three predefined buckets had at least 20
trades in both development and validation and lost under the two-cent stress in both partitions.

| Repeating weakness | Trades | Base P&L | Two-cent stress | Maximum drawdown |
|---|---:|---:|---:|---:|
| Entry price 65–69 cents | 125 | -$1.6507 | -$4.0860 | $6.5615 |
| Fast/slow variance ratio below 0.50 | 470 | +$7.3311 | -$2.2081 | $8.0098 |
| 06:00–11:59 UTC | 214 | -$0.3715 | -$4.7381 | $6.0360 |

These groups overlap. For example, 71 trades were both 65–69-cent entries and in the low-variance-ratio group;
107 were both low-variance-ratio and 06:00–11:59 UTC. The losses therefore cannot be added or described as three
independent effects.

Twelve predefined buckets were positive under two-cent stress in both partitions. The larger, more useful
descriptive strengths were NO-side entries (+$10.0974 stressed), 45–54-cent entries (+$13.3966), 75–79-cent
entries (+$8.9220), a 0.50–0.99 fast/slow variance ratio (+$9.7705), and 18:00–23:59 UTC (+$13.6082). Nine other
buckets changed stressed-P&L sign between development and validation. That instability is evidence against
stacking several filters from this report.

## Post-hoc filter check

Removing only the 65–69-cent bucket was the least destructive single hypothesis. It retained 713 trades, or
4.85 per observed day, with +$31.3116 base P&L, +$16.2750 under two-cent stress and $5.0989 maximum drawdown.
Development retained +$10.8558 of stressed P&L; validation retained +$5.4192 and its drawdown fell to $4.1838.

Removing all three repeating-weakness labels retained only 225 trades, or 1.53 per day. Those trades made
$18.3279 and +$13.2803 under two-cent stress, but the frequency loss is severe. The union of removed trades was
still positive in validation after stress because the overlapping definitions also discard profitable trades.

These removal figures are exploratory and were calculated after viewing both partitions. They are not an
out-of-sample result, a promotion gate, or permission to change the live bot. The simplest next candidate is the
exact Study 023 signal with only the 65–69-cent entry band excluded. It must be registered before a one-time
evaluation on the sealed holdout, with no further tuning after that result.

## Decision

Study 025 explains part of Study 023's inconsistency but does not prove a repaired edge. It found one simple,
testable candidate and also showed that aggressive multi-filtering would cut the strategy to about 1.5 trades per
day. The current live strategy, sizing and execution rules remain unchanged.
