# Strategy comparison 001 — September 21, 2026

**No strategy is ready for real money or parameter promotion.** Basic fair value is the only positive default in both inspected periods, but its validation profit depends on one large win. The current tail and adaptive settings fail this initial profitability screen. That rejects promotion of these settings; it does not establish that the broader ideas can never work.

## Results you can review

Net simulated trading P&L after modeled fees, with three independent $100 accounts and up to $1 risk per market. Validation is the next portion of each original continuous account, not a fresh $100 restart. Hosting costs are separate. Parameters were unchanged throughout.

| Strategy | Development P&L | Settled trades | Validation P&L | Settled trades |
|---|---:|---:|---:|---:|
| Basic fair value | $+16.33 | 106 | $+5.80 | 39 |
| Tail underdog | $-6.14 | 47 | $-3.17 | 16 |
| Adaptive volatility | $-0.25 | 120 | $-8.11 | 42 |

| Strategy | Drawdown: development / validation | Fill rate: development / validation | Fees: development / validation |
|---|---:|---:|---:|
| Basic fair value | $9.27 / $9.03 | 67.1% / 86.7% | $2.43 / $0.93 |
| Tail underdog | $9.87 / $6.47 | 82.5% / 59.3% | $1.98 / $0.68 |
| Adaptive volatility | $10.04 / $10.22 | 71.0% / 72.4% | $2.39 / $0.97 |

Drawdown treats open positions at cost, so it is not a worst-case liquidation loss. All selected filled positions are settled at the frozen cutoff; no unresolved selected-market outcomes were dropped. Order refusals primarily came from prices moving beyond the limit, with some insufficient integer depth. Per-decision rejection counters were not partitionable and are not presented as group-specific counts.

## Why the positive result is fragile

Basic fair value made $5.8028 in validation. Its largest winner made $14.0726; without that one win, the other validation trades total **-$8.2698**. Its development profit becomes **-$0.9365** without the three largest wins. These are concentration diagnostics, not a rule for deleting valid winning trades. A strategy that relies on rare wins needs much more evidence about how often those wins occur and whether they can be executed.

The large validation win was separately checked against 12 original archived segments. The model submitted a NO limit at $0.062 and later simulated 15 contracts at $0.058, with 2,038.81 contracts displayed at arrival. The official recorded finalization was NO. Price, depth, timing and settlement checks passed. That supports the paper ledger, not a guarantee of real exchange execution. [Targeted audit](validation/comparison-001-largest-win-audit.json).

Basic development profit was concentrated on September 18 (+$18.34), followed by -$0.27 on September 19 and -$1.74 in the short September 20 development portion. Its later September 20 validation portion made +$5.80. These are unequal partial-day windows, not a stable daily return estimate.

For tail entries, the model's average predicted win probability was 36.3% versus 17.0% realized in development, and 33.7% versus 18.8% in validation. This is a warning that the estimated probabilities may be too optimistic on the trades it selects. The small sample does not establish the size or persistence of that error. Adaptive volatility was near flat in development and lost $8.11 in validation; its current blend did not improve the comparison.

## Parameters actually tested

| Setting | Registered value |
|---|---|
| Starting account | $100 independently per strategy |
| Maximum order cost | $1 including modeled fees |
| Entry window | 5–300 seconds before close |
| Minimum modeled net edge | 4 percentage points |
| Execution | Delayed IOC, 500 ms; best available level within the limit |
| Quote / index freshness | 2 seconds / 3 seconds |
| Position policy | One filled entry per market; hold until official finalization |
| Tail filters | 5–135 seconds remaining; cheaper outcome at most $0.35; absolute modeled z-score at most 1 |
| Adaptive volatility | 70% recent 60-second variance, 30% longer 600-second variance |
| Fee assumption | Quadratic coefficient 0.07; $0.0001 balance precision; supported event/series metadata required |

The tail distance filter is volatility-normalized distance, not a fixed dollar gap from the threshold. None of these parameters has been optimized or proven. Direct-member precision remains an unconfirmed account assumption; the earlier cent-rounding stress was a separate small execution audit, not a stress test of this entire dataset.

## Frozen scope and protection against selection bias

The source is stopped v5 dataset `df8b028c26294ac68ee34f2b37f32ce3`: 95,466,332 events across 982 verified archived segments. The checkpoint and catalog prefix match, the original registration/config were checked, and cash/reservations reconcile. The comparison attributes the already-computed registered forward ledger; it does not claim a new full raw-event replay or a new parameter backtest. The first archived segment was reverified during freezing and the largest win was separately rechecked in raw data; the whole 95-million-event archive was not downloaded again.

- Train: 140 markets closing 2026-09-18T14:30:00+00:00 through 2026-09-20T01:15:00+00:00.
- Validation: 47 markets closing 2026-09-20T01:30:00+00:00 through 2026-09-20T13:00:00+00:00.
- Holdout: 47 whole markets remain undisclosed; no holdout performance report was produced.
- Two markets had not closed at the frozen cutoff and stay outside the partitioned screen.
- One startup market was only partially captured; it remains flagged and contributed no realized P&L to any strategy in this screen.

The split was committed before viewing v5 P&L. No settings changed between development and validation. Training-trade settlements preceded the first validation decisions for all strategies. Only three UTC dates are represented in development and one in validation, with overlap in calendar date across the time boundary; these are not independent multiweek samples. The predeclared 20-day uncertainty gate is not met, so there is no confidence interval or reliability claim. Earlier v5 fill counts and accounting identities had been inspected during commissioning, and that prior disclosure is recorded.

If settings change after inspecting these results, both opened periods are development evidence for that new study. Do not reuse this validation score as untouched evidence for a retuned model. Future grid choices must be declared before running, with genuinely later validation and the held-back set preserved until appropriate.

## Decision and next work

Keep all defaults paper-only and unchanged while data accumulates. Prioritize checking whether basic fair value's rare wins survive broader execution stresses and additional days; do not promote it from this result. Do not tune tail or adaptive parameters merely to make this short history look profitable. The next parameter study requires enough distinct days, a small declared candidate grid, development-only selection and later independent validation. Continue recording on Railway; no new service, live order capability or deployment was needed for this comparison.

Reproducible records: [protocol](COMPARISON_PROTOCOL.md), [frozen manifest](validation/comparison-001-manifest.json), [full aggregate results](validation/comparison-001-results.json). The protected raw checkpoint remains on the existing Railway volume at `/data/comparisons/v5-001`; raw account histories and credentials are not committed.
