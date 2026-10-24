# HFT feasibility diagnostic 030

Run October 23, 2026 after the first frozen Study 029 replay. This is an
offline, post-hoc diagnostic on the already-viewed 39.2045-hour Study 029 tape.
It is not preregistered, is not evidence of profitability, and cannot promote a
strategy, change the Demo runner, or authorize Jev.

## Purpose

Study 029 produced two quote intents and no conservative queue fills. This
diagnostic asks whether that was caused by its admissibility filters or by a
lack of economically usable passive quoting opportunities in the tape.

Every run used the same 76 main segments, 172 public-trade segments, 500 ms
acknowledgement, back-of-displayed-queue placement, no cancellation credit,
strictly later non-block public trades only, and exclusion of ambiguous
exchange/receipt ordering. It covered three UTC dates and 2,049,350 public
trades.

## Results

| Diagnostic | Deliberate change | Intents / acknowledgements / plausible fills | Result |
| --- | --- | --- | --- |
| 030a, relaxed admissibility | 5--300 seconds, probability 0.02--0.98, raw/market gap at most 0.25 | 2 / 1 / 0 | Removing those filters did not create an additional executable passive opportunity. The formerly excluded observations mostly failed the fee-adjusted passive-value test. |
| 030b, break-even passive value | 030a plus zero adverse-selection reserve and a 30-second lifetime; a quote still needed nonnegative fee-adjusted value | 2 / 1 / 0 | A longer quote life did not change the result. |
| 030c, raw queue-turnover probe | 030b plus a minimum edge of -$1 solely to allow economically invalid quotes | 4 / 2 / 0 | Even this non-tradable mechanics probe found zero plausible fills. |

## Interpretation

The observed tape provides no evidence that passive HFT can obtain enough
queue fills for a small BTC 15-minute bankroll under the conservative model.
It does not prove that fills are impossible: the sample is only three dates,
and it has no individual order-queue events. It does show that widening the
baseline thresholds cannot justify a new strategy from this tape.

The right next evidence is forward data, not a larger parameter grid: retain
the Demo runner as an execution/reconciliation harness and extend the
trade-plus-book archive until it has materially more days. A new candidate is
only worth registering if that forward evidence shows real passive fills with
reconciled fee and inventory records. Jev remains disabled.
