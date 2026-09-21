# Execution audit — September 18, 2026

The simulator's sampled fills agree with the preserved books and its original forward ledger. This is a correctness check on the simulation, not confirmation that real orders would fill or that any strategy is profitable.

## Scope and evidence

Frozen v3 dataset `6907fda78df14d2fb2c182a1107396a0`, archived segments 0–23: 2,397,032 events through September 17, 18:35:37 UTC. Five distinct markets had baseline fills; the first market is a partial startup capture. Eleven baseline fills (4 basic, 2 tail, 5 adaptive) exactly match the original forward checkpoint in timing, quantity, price, fee and cost.

A separate book reconstruction uses the feed's YES-coordinate bid levels directly. All 57 simulated fills across six scenarios pass checks for timing, limit, raw price/depth, freshness, independently calculated fees, reservation/risk caps and nonnegative cash. Cash, reservations and one-fill-per-market constraints reconcile for every account. The maximum first-event sampling delay beyond configured arrival was 12.92 ms in this sample; that is not a measured exchange round-trip latency.

Representative tail fill: six NO contracts at $0.14, against 5,010.48 displayed contracts; $0.0506 modeled fee and $0.8906 total cost, after the configured 500 ms latency plus 3.80 ms to the next received event. This verifies arithmetic and observed liquidity, not queue priority or actual execution.

Evidence: [full execution audit](validation/execution-sensitivity-v3.json), [current official fee checks](validation/fee-reference-2026-09-18.json).

## Sensitivity results

Net simulated trading P&L in dollars, separate $100 starting accounts. Infrastructure costs are excluded. This is a tiny inspected commissioning sample, including startup data, with too few trades or days for statistical inference. No parameters were selected from these results.

| Scenario | Basic fair value | Tail underdog | Adaptive volatility |
|---|---:|---:|---:|
| baseline_500ms | -0.4413 | -1.7377 | -1.2127 |
| latency_1500ms | -1.6705 | -0.7947 | -2.8466 |
| latency_3000ms | -0.2328 | -1.6223 | -0.9805 |
| half_displayed_depth | -0.4413 | -1.7377 | -1.2127 |
| cent_balance_rounding | -0.6100 | -1.7500 | -1.8300 |
| combined_adverse | -1.2500 | -1.7200 | -1.2600 |

The combined adverse case uses 3-second latency, 25% displayed depth, cent balance rounding, double the fee coefficient and a 500 ms quote-age limit. Half depth alone did not affect these tiny orders because displayed liquidity was ample. Slower execution is not monotonically worse on a small historical path: it changes entry prices and which trades occur. No strategy is promoted or rejected from these results.

## Fees and fixes

The current [official fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf), effective July 7, 2026, states the general taker coefficient of 0.07 multiplied by the contract multiplier, and no settlement fee. The [API rounding documentation](https://docs.kalshi.com/getting_started/fee_rounding) specifies six-decimal trade-fee rounding and balance alignment of $0.0001 for direct members or $0.01 for non-direct members. The simulator's aggregate single-price fill agrees with that calculation. Actual multi-fill matching and fee accumulation have not been empirically certified.

Recorded series metadata is quadratic with multiplier 1. A September 18 public-reference check found no event overrides on the five sampled traded markets. These later lookups were never added to earlier receipt streams. Historical event-level fee metadata was missing, so the old reports retain that qualification.

The new v5 source captures event metadata approximately once a minute, checks its series identity, applies event overrides before series defaults, and rejects absent/stale/unsupported fee metadata at both decision and arrival. Event freshness is two minutes; series freshness is thirty minutes. Inactive markets now block entries and pending fills. Regression tests cover missing/stale fees, higher multipliers, unsupported schedules, nonfinite values, inactive markets, independent depth tampering and fee arithmetic. The September 18 local run passed 55 tests and Ruff. GitHub subsequently exposed an uptime-dependent initial fee lookup; the September 20 correction now passes 58 tests, Ruff and the production container check. [Passing CI](https://github.com/kaiau00/kalshi-research-lab/actions/runs/35549267859).

The account channel has not been independently verified; direct-member precision remains the registered default and cent precision was separately stressed. No account balances, account transactions or live orders were accessed.

## Reproduction and next gate

The historical audit ran with engine source from commit `0a51567` (the v4 archive change did not alter the v3 engine) and the audit script now committed in `02a94e7`. To reproduce, use that original engine source on PYTHONPATH with `scripts/audit_execution.py --root <v3 archive catalog> --max-segments 24 --output <new report>`, supplying bucket credentials through the environment. The artifact records source/script hashes, dataset, terminal archive hash and exact configuration. The current stricter engine deliberately rejects old records without event fee metadata; do not backfill missing metadata to make it trade.

September 20 follow-up: v5 accumulated over 95 million events and 981 verified archives, with no replay backlog. Fee metadata was fresh (2.86 seconds at the checked cutoff); source/checkpoint hashes, event totals and paper cash/reservations reconcile. The active market passed the new fee guard. See [live evidence](validation/fee-guard-live-v5.json). The startup-only correction is registered separately in v6, preserving v5 intact.

Next: compare the larger frozen v5 sample under its registered engine/configuration and continue prospective v6 collection across more market conditions. Only then begin development-set parameter comparisons, followed by frozen untouched/forward validation. Full bare-volume disaster recovery and sustained compact-cost measurement remain separate open operations checks.
