# Deterministic HFT Baseline Study 029

Declared October 23, 2026. This protocol was frozen before the first P&L replay. It defines a separate Kalshi
Demo experiment and a queue-conservative replay. It does not authorize production orders or any Jev call.

## Question

Can a small, deterministic passive market maker earn positive net P&L in BTC 15-minute Up/Down markets after
maker fees, measured latency, displayed queue position, adverse selection, inventory risk and concentration are
accounted for?

## Fair value and quotes

The raw settlement probability uses the existing conditional Brownian model of the final 60 BRTI source seconds.
One-second return variance is 70% from the trailing 60 seconds and 30% from the trailing 600 seconds. The market
reference is the equal-weight average of the binary midpoint and top-level microprice. Raw and market probabilities
are pooled in log-odds space with 75% raw weight and 25% market weight.

The engine evaluates from 30 through 300 seconds before close. Pooled YES probability must lie from 0.10 through
0.90 and raw-versus-market disagreement may not exceed 0.12. The binary spread must be at least $0.02. The quote
joins the best bid, improving it by one cent only when the spread is at least $0.04, and remains one tick below the
opposite ask. A quote needs at least $0.001 expected edge after a conservatively modeled quadratic maker fee and a
separate $0.001 adverse-selection reserve.

Inventory reservation values use the exact CARA certainty equivalent for a binary terminal payoff:

```text
CE(x,p) = -log((1-p) + p*exp(-gamma*x)) / gamma
yes reservation = CE(x+1,p) - CE(x,p)
no reservation  = 1 + CE(x-1,p) - CE(x,p)
gamma = 0.02
```

## Execution and risk

- Kalshi Demo, Predictions exchange index 2, subaccount 0, KXBTC15M only.
- One contract per quote, at most two resting quotes and at most five contracts of absolute net inventory.
- At most one market may have nonzero inventory; maximum unsettled gross premium is $5.
- Post-only good-till-canceled orders, exchange cancellation-on-pause and an integer expiration no more than three
  seconds away. The runner refreshes once per second.
- Durable intent is committed before every create and cancel. A timeout or unknown response blocks all new writes
  until the exact order is reconciled. POST is never retried automatically.
- Exchange order identity, cumulative fills and cumulative costs may never move backward. Account resting orders
  and positions must exactly equal the durable ledger. Any external exposure blocks the experiment.
- `STOP` and `PAUSE_QUOTES` cancel tracked quotes and prevent new quotes. The service has no production host,
  credential fallback or production order path.

The historical replay adds a frozen 500 ms acknowledgement delay. A quote joins behind all displayed size at its
price. Cancellations ahead provide no queue credit. Only a strictly later, non-block public trade at the exact price
and correct maker direction may consume the queue. Exchange-time and local receipt-time ordering must both agree;
ambiguous ordering is excluded.

## Evidence gate

The baseline is credible only after all gates pass on untouched forward data:

- at least 20 distinct UTC dates and 1,000 plausible queue fills;
- positive P&L after fees and under the conservative queue model;
- positive P&L after removing the three largest winning markets;
- positive P&L in at least four of five chronological blocks;
- positive P&L after one cent of adverse movement per fill;
- zero unresolved simulated exposure.

Two-cent stress, fees, drawdown, fill frequency, quote rejections and unresolved exposure are always reported even
when they are not the deciding gate. A short preliminary slice cannot promote the baseline.

## Jev gate

Jev stays disabled until every baseline gate passes. If that happens, the same frozen evaluation set compares:

1. baseline alone;
2. baseline plus a monotone Jev veto that may only remove quotes;
3. baseline plus a Jev directional filter that may restrict the allowed side.

Jev may not set price or size, create a quote, bypass a safety control or convert an invalid baseline action into a
valid one. Its model/version, typed prompt, cache key and failure-to-cancel policy must be frozen before comparison.
No Jev result may be used to retune the baseline on the same evaluation data.

## Implementation

- Pure quote math: `src/hft_demo/engine.py`
- Demo-only client and safety validation: `src/hft_demo/client.py`
- Durable ledger and reconciliation: `src/hft_demo/journal.py`
- Separate runner/dashboard: `src/hft_demo/runner.py`, `src/hft_demo/app.py`
- Queue-conservative replay: `src/hft_research/baseline_replay.py`
- Frozen identity: `src/hft_demo/registration.py`

The first frozen replay result is recorded in
[the preliminary result](DETERMINISTIC_HFT_BASELINE_STUDY_029_PRELIMINARY_RESULT.md).
