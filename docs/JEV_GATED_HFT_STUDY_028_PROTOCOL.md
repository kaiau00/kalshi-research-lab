# Jev-Gated HFT Feasibility Study 028

Declared on 2026-10-22 under registration SHA-256
`d72707eb0c78c8456b47ed6dc44719f0bd13a79fb15cdabcee9ba77582e79466`.

Study 028 is read-only research for `KXBTC15M`. It cannot submit a demo or production order, change the selected
production runner, change its risk, or call Jev from the deployed service. A later execution phase requires its
own frozen protocol and explicit authorization.

## Hypothesis and attribution

The baseline is a deterministic, settlement-aware engine. It estimates the probability of the exact BRTI
settlement event, translates that probability into fee-aware executable value, and proposes passive quotes or a
rare stale-quote IOC only after hard latency, inventory, spread and expected-value checks.

Jev is a supervisor. Its typed response may classify the regime, allow both quote sides, restrict quotes to one
side, cancel all quotes, or veto an aggressive action. It may never create an action the deterministic engine did
not authorize, choose quantity, change a price, bypass a hard risk check, or reconcile an order. A timeout,
malformed response or unavailable pinned model maps to `cancel_all` with taker permission disabled.

Three arms receive identical timestamped inputs:

1. **A — mathematical baseline:** no Jev decision affects the action.
2. **B — veto:** Jev may cancel the complete action or veto taking.
3. **C — direction gate:** Jev may also restrict passive quotes to YES-only or NO-only.

Every candidate saves the baseline action, canonical Jev input digest, cached typed response, final permitted
action, later markouts and eventual official result. The study pins `jev-1.13.0`; changing the model creates a new
study.

## Two data stages

The existing v6 archive may be used for fair value, opportunity frequency, counterfactual quote placement,
short-horizon markout, regime classification, and Jev helped/hurt/tied attribution. It cannot establish passive
fills because it has no public trade channel or observed queue acknowledgements.

A new forward tape is required for maker validation. The implemented hosted design preserves public trades in a
separately registered trade-only sidecar and joins them later to the existing unchanged v6 order-book, BRTI,
market, fee and outcome streams. Both datasets retain exchange timestamps, local receipt timestamps and
reconnect/gap markers. The join excludes ambiguous ordering. The sidecar is disabled by default, has separate
hot and archive caps, and has no account or order API. Its registration and archive prefix must be frozen before
profitability is evaluated. The production runner and main recorder remain unchanged.

Kalshi's documented Predictions channel is `trade`. Each update includes a unique trade ID, market ticker,
complementary YES/NO fixed-point prices, fixed-point count, taker outcome/book side, block-trade marker and exchange
timestamp. Block trades cannot advance a displayed-queue simulation. See the official
[Public Trades](https://docs.kalshi.com/websockets/public-trades) schema.

## Conservative maker simulation

- Acknowledged quotes join behind all displayed size at their level.
- A fill requires public trades to consume the simulated quantity ahead and then our quantity.
- Displayed cancellations do not move us forward unless a frozen observable attribution rule permits it.
- Partial fills, cancel latency and fill/cancel races remain exposure.
- Results are repeated with doubled latency and one- and two-cent adverse execution stress.
- Taker fills use the first observed executable level after the frozen latency and include the exact applicable fee.

## Evaluation

Report net P&L after fees, fill count and rate, spread capture, inventory, maximum drawdown, positive-day and
five-block consistency, top-three-winner concentration, calibration, queue-model sensitivity and 1/5/15/30-second
post-fill markouts. For Jev, additionally report call latency, timeouts, abstentions, confidence calibration, cost,
and decisions helped/hurt/tied relative to Arm A.

Review for a demo proposal only after at least 20 distinct UTC dates and 1,000 plausible simulated fills. The
chosen arm must be positive after fees, under the conservative queue model, without its three largest winners,
and in at least four of five chronological blocks. Jev must improve out-of-sample net P&L or reduce adverse
selection loss or maximum drawdown by at least 20% without eliminating practical fill frequency. The mathematical
baseline must remain positive on its own.

If a later demo is authorized, the initial proposal is one-contract orders, at most $5 total inventory, at most
one aggressive position, no Kelly sizing, and fail-closed controls. Those limits are a future proposal rather
than current order authority.
