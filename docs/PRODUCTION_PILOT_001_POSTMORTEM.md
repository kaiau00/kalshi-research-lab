# Production pilot 001 postmortem

Status: **paused by `/data/production-adaptive-001/STOP` on October 7, 2026. Do not resume without a new
explicit user instruction.** The ledger, fills, settlements, and remaining account balance are preserved.

## Final observed account result

| Metric | Result |
|---|---:|
| Settled markets | 23 |
| Wins / losses | 12 / 11 |
| Realized net P&L | **-$24.2438** |
| Remaining shard-2 cash | **$75.7562** |
| Winning-trade P&L | +$4.8223 |
| Losing-trade P&L | -$29.0661 |
| Maximum realized drawdown | $24.2438 |
| Longest loss streak | 5 |
| Unresolved orders | 0 |

One final order filled before the stop file reached the already-running service. The protected production status
then reported `stopped_by_file`; no later submission is permitted while the file remains present.

## Execution and accounting audit

The loss was not caused by a reversed order side, wrong threshold, settlement mismatch, or excess order size.

- All 23 exchange responses matched the intended YES/NO outcome side.
- All inferred thresholds matched the recorded Kalshi `floor_strike` and strict/inclusive comparison.
- All journal settlements matched the official market result and tracked fill quantities and costs.
- All orders were terminal IOC fills; there were no resting or unresolved orders.
- Maximum all-in cost was $2.8963 and minimum was $2.2894, within the frozen $3 cap.
- Recorded edge calculations matched the configured formula. Two model probabilities were clipped at the declared
  0.999 ceiling, which explains the only raw-normal-CDF audit differences.

## Model failure

The live model assigned an average 75.85% win probability but won 12 of 23 trades, or 52.17%. Based on its own
probabilities and actual contract counts and costs, it expected +$9.7792. It realized -$24.2438. The difference is
too large to treat the probability estimates as calibrated evidence.

| Filled outcome-price group | Trades | Wins | Net P&L | Mean model probability |
|---|---:|---:|---:|---:|
| At or below $0.35 | 5 | 0 | **-$13.8901** | 31.67% |
| Above $0.35 through $0.70 | 5 | 1 | **-$8.8733** | 71.86% |
| Above $0.70 | 13 | 11 | **-$1.4804** | 94.38% |

The strategy therefore lost both through low-priced outcomes that never produced the required rare win and
through medium/high-probability estimates that were too confident. Entries with 225–275 seconds left went 0 for
6 and lost $15.6157. YES entries lost $14.3409; NO entries lost $9.9029, so a simple side inversion does not
explain the result.

The longer production-data replay is also fragile. Its registered $1 adaptive account has 1,198 settlements and
+$53.7390, but its three largest winners contribute $86.1073. Removing those three leaves **-$32.3683**. Only 8
of 18 UTC days are positive, and its 56.59% win rate trails its 64.19% average predicted probability. The live
drawdown is consistent with the ordinary losing distribution once the rare large winners do not arrive.

This matches the earlier exact-arrival audit: demo performance did not transfer cleanly to production quotes, and
the production-qualified subset was negative before adverse-price stress. The demo balance was not reliable
evidence of a production edge.

## Live/replay divergence found

The registered production replay traded the same 23 tickers during the pilot window and lost $3.8518 at its
registered $1 cap. It selected the same side as live execution for 21 of 23 markets. This confirms that the main
loss is present in the production-data research model, rather than being created by the exchange adapter.

One implementation mismatch still requires correction before any future pilot. The replay counts every signal as
an attempt before its 500 ms arrival, including a signal that later cancels because the limit is no longer
marketable. The production runner reconstructs attempts only from submitted durable intents. It does not journal
or count an arrival-time cancellation that never reaches the exchange, so subsequent loops can exceed the frozen
three-attempt decision limit. On `KXBTC15M-26OCT072145-45`, replay used three attempts and eventually filled NO;
live execution later filled YES and lost $2.7639. The runner's stricter account-exposure guard and different
wall-clock sampling can also shift entry time relative to replay.

This mismatch does not rescue the strategy: the production replay was negative over the same window, 21 sides
matched, and the broader replay depends on three outlier wins. It does mean the production adapter was not an
exact implementation of the frozen simulator and must not be restarted unchanged.

## Required work before any future real-money run

1. Keep the current runner paused and preserve its ledger.
2. Journal every signal and arrival cancellation so the three-attempt limit survives loops and restarts.
3. Make the live and replay exposure policy and decision clock identical, then prove event-by-event parity on a
   production-data shadow run.
4. Add independent daily, cumulative-drawdown, trade-count, and calibration circuit breakers.
5. Evaluate calibration and P&L without the largest winners on a new preregistered production-data period.
6. Do not select a price or timing filter from these 23 exposed trades and describe it as validated.
7. Require explicit user authorization before removing the stop file or submitting another production order.

