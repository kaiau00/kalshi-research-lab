# Parameter Study 004 results

**Result: no winner.** None of the 40 preregistered configurations passed all promotion gates. This was a development-only replay, so even a passing configuration would have required a new prospective study.

## Frozen input

- Dataset `e2d5cb33e7c44660809b531f03d4b4e3`, segments 0–4344
- 425,326,032 receipt-ordered events across 10 UTC dates
- Study source `504fb4ad9fedfba2889c9d651f544743ee669aa25e5a3115aa448a5588f254f1`; registration `db6e4b812a94576c18ba6cd6bc9be82f95d8abda57192c5341641a0ebd6d58b1`
- $100 independent simulated bankroll per configuration, $1 maximum modeled cost per market, 500 ms delayed IOC, recorded fees and official outcomes

## Gate results

| Preregistered gate | Configurations passing |
|---|---:|
| At least 100 settlements | 32 / 40 |
| Positive headline P&L | 7 / 40 |
| Positive after removing three largest winners | 0 / 40 |
| Positive with two-cent worse fills | 1 / 40 |
| Positive in at least four of five chronological blocks | 0 / 40 |
| Positive on more than half of UTC dates | 0 / 40 |
| Maximum drawdown no greater than $20 | 11 / 40 |
| Log loss no worse than raw 4% reference | 6 / 40 |
| All gates | 0 / 40 |

## Highest headline results

| Configuration | P&L | Without top 3 | Two-cent stress | Settlements | Positive blocks | Positive days | Max drawdown |
|---|---:|---:|---:|---:|---:|---:|---:|
| `window_blend25_e06_30_180` | $+19.3280 | $-32.3316 | $+0.3924 | 294 | 3/5 | 40% | $43.68 |
| `signal_calibrated_e04` | $+13.1496 | $-130.1579 | $-122.5525 | 667 | 3/5 | 30% | $113.59 |
| `signal_blend25_e04` | $+7.6034 | $-39.6997 | $-26.0692 | 551 | 2/5 | 30% | $40.00 |
| `signal_raw_e04` | $+5.6672 | $-42.5253 | $-41.8535 | 616 | 3/5 | 40% | $31.06 |
| `signal_raw_e08` | $+5.6476 | $-41.6942 | $-22.6148 | 432 | 3/5 | 40% | $34.51 |
| `signal_blend25_e06` | $+3.4136 | $-30.3622 | $-18.7434 | 428 | 2/5 | 40% | $39.62 |
| `signal_blend50_e04` | $+2.4188 | $-30.4001 | $-16.9252 | 415 | 2/5 | 40% | $32.58 |
| `signal_raw_e10` | $-0.8356 | $-34.6114 | $-23.7731 | 360 | 2/5 | 50% | $36.82 |
| `window_raw_e06_30_120` | $-2.1172 | $-61.4136 | $-34.6947 | 259 | 1/5 | 20% | $50.82 |
| `window_blend50_e06_30_180` | $-3.4673 | $-24.4902 | $-11.1668 | 187 | 2/5 | 40% | $18.66 |

## What failed

The best headline configuration was `window_blend25_e06_30_180`: a 25% log-odds blend toward the market, 6% minimum edge, and a 30–180 second entry window. It made $19.3280 across 294 settlements, but its three largest winners contributed $51.6596. Removing them changes the result to -$32.3316. It was positive in only three of five chronological blocks and four of ten UTC dates, with a $43.68 maximum drawdown.

Its largest winners bought very cheap contracts: $0.035 for 25 contracts and $0.021 for 21 contracts. Those two markets produced $44.5945 of profit. This payoff shape explains both the attractive headline result and the instability: many losses are close to the full $1 risk cap, while a few low-price wins pay many multiples.

Calibration improved probability log loss and headline P&L in some settings, but did not create robust trading returns. `signal_calibrated_e04` made $13.1496, while its three largest winners contributed $143.3075; without them it lost $130.1579, and two-cent execution stress produced -$122.5525. The raw 4% reference made $5.6672 but fell to -$42.5253 without its three largest winners.

Spread caps and two-second quote persistence did not solve the problem in their preregistered combinations.

- Signal: 6/20 positive; best `signal_calibrated_e04` at $+13.1496.
- Time window: 1/10 positive; best `window_blend25_e06_30_180` at $+19.3280.
- Spread cap: 0/4 positive; best `spread_blend50_e06_30_180_s03` at $-3.4673.
- Two-second persistence: 0/6 positive; best `persist_blend50_e06_30_180_s03` at $-18.5532.

## Decision

Study 004 selects no configuration. The completed report does not justify Study 005 or a change to the demo strategy. Candidate Study 003 remains unchanged and must accumulate at least 20 forward UTC dates before its predeclared review. New segments after the Study 004 cutoff remain untouched forward evidence.

The complete 40-configuration metrics and selected trade-level concentration examples are preserved in [the sanitized JSON summary](validation/parameter-study-004-summary.json).
