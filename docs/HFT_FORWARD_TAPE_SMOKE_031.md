# HFT Forward-Tape Replay Smoke 031

**Classification:** exploratory replay and pipeline check, not a preregistered promotion study.

## Purpose

Exercise the deterministic HFT baseline against synchronized, immutable forward
order-book and public-trade archives before spending more data budget or adding
Jev. The replay uses only recorded events and never reaches an order endpoint.

## Slice

- Decision interval: 2026-10-23 20:30:00–21:00:00 UTC
- Main order-book archive: 4 verified segments, 35,923,136 compressed bytes
- Public-trade archive: 7 verified segments, 11,305,987 compressed bytes
- Download cap: 50 MiB; selected input: 47,229,123 bytes
- Public non-block trades replayed: 128,988

## Integrity repair

The initial merge treated an `ok` subscription acknowledgement from the
separate public-trade sidecar as a book-feed sequence message. That could create
a false sequence gap and invalidate the replay book. The baseline now applies
market state only to websocket records marked `book_convention: yes_price`;
sidecar records are used only for `trade` events. A regression test covers this
boundary.

## Result

- Quote intents: 0
- Acknowledged quotes: 0
- Conservative queue fills: 0
- Fees and net P&L: $0
- Unresolved inventory: none
- Credible edge: **false**
- Jev comparison authorized: **false**

The repaired replay reached eligible decision points. Its frozen filters then
rejected them: 589 outside the time window, 364 for raw-model/market
probability disagreement, 59 for no fee-adjusted passive edge, and 19 for
extreme pooled probability. Zero fills over a single half-hour neither proves
nor disproves the idea, but it gives no reason to add Jev or loosen the strategy
until a larger, preregistered sample is evaluated.

## Next evidence step

Run bounded daily slices until the forward tape covers enough representative
sessions, then run the preregistered 20-date, 1,000-conservative-fill baseline
study. Only if every frozen gate passes may the same tape be used to compare the
baseline with Jev veto and directional-filter variants.
