# Data validation — 2026-09-17

**Decision: captured-data integrity passes; the system is not ready for strategy validation or uninterrupted collection.**

Audited every one of 5,334,381 events captured between 04:20:11 and 10:05:23 UTC on September 17 (00:20–06:05 EDT). The database prefix is fixed at event 5,334,381, hash `73e23205576ef1f36f4f43fc4483bb0cf76eb3365857f33c0f0b227ee0bf1bf4`. Production source was `ab08ff3`. No performance evaluation or parameter selection was performed.

## Passed

- SQLite structural check and every event hash pass. Receipt IDs and timestamps are ordered. Zero malformed frames, benchmark timestamp inconsistencies, or in-session sequence discontinuities.
- All 16 captured market definitions match the official API for thresholds, times, comparison direction and rounding. All 15 captured results and settlement prices match current finalized records. Thresholds remained numerically stable.
- All 15 completed markets contain the entire correct settlement minute. The close-exclusive mean reproduces all 15 official settlement prices exactly to cents.
- Of 4,939,553 book deltas, 4,939,528 arrived within 250 ms of their source timestamps and 25 within one second. Five of 13,295 benchmark messages exceeded 250 ms; one took between three and ten seconds. Preserve late data and reject stale inputs at decision time.

## Blockers

1. **Settlement boundary bug — fixed locally, deployment pending.** The former forecast used `(close-60s, close]`, matching the WebSocket quarter-hour accumulation field. Official settlements match `[close-60s, close)`, also matching the trailing average at close. The former calculation differed by $0.02–$0.74 in all 15 completed markets, although their yes/no outcomes happened to agree. The forecast and regression tests now use the verified window. Existing reports are commissioning artifacts, not validated strategy evidence. The changed source needs a new forward registration.
2. **Opening coverage is incomplete.** Four of the 14 markets fully spanned by recording contain all 900 benchmark seconds. First book snapshots arrive 15.2–53.4 seconds after open. Discovery polls every 30 seconds and rebuilds the entire WebSocket connection when the market set changes. Preserve BRTI across rollovers and acquire newly available books sooner. Never invent or forward-fill the missing observations.
3. **Capacity stopped collection.** The recorder halted at about 06:05:23 EDT at its roughly 2 GB safety boundary. Replay also exceeded its two-million-event ceiling. The dashboard remains available, but health and readiness are 503. Recording remains stopped. No storage limits or spending settings were raised. Archival/retention and bounded replay must be resolved before long-term restart.
4. **Final outcome lifecycle.** Three recorded results stopped at `determined` and were never refreshed to `finalized`. Their values agree with current final results, but the recorder should retain later finalization and flag revisions.

The first and last markets are partial and remain labeled as such. The official listing contains no BTC 15-minute markets between the 07:00 and 09:15 UTC closes. There are 16 explicit stream-session markers and one final stop marker; no in-session sequence discontinuities were found. Empty or one-sided books are observed liquidity, not automatically recording defects.

## Evidence and reproduction

- `validation/data-audit-legacy-window.json`: original exhaustive integrity, sequence and coverage audit, schema 1. Its settlement fields expose the former close-inclusive error.
- `validation/settlement-window-comparison.json`: independent raw-tick scan comparing both adjacent windows with the official values and the exchange trailing average at close.
- `validation/official-reference-check.json`: current official values checked separately after recording. These are audit evidence, never backdated observations.
- `scripts/audit_data.py --db <recording>`: reusable read-only frozen-prefix auditor, now schema 2 with the corrected window. A local run with changed source will intentionally fail the original registration's source-hash match; do not rewrite it.
- 37 tests pass, including missing-first-tick rejection, correct boundary averaging and book-coverage accounting. Ruff passes.

Book coverage measures actual receipt-time intervals with valid, two-sided quotes and the existing two-second freshness rule. It is not simulated-fill validation. Raw recordings and secrets were not committed.

[Kalshi's averaging documentation](https://docs.kalshi.com/websockets/cfbenchmarks-value) distinguishes the two feed average fields. The settlement-window conclusion is supported by the 15 exact official-value comparisons, not an assumption that the quarter-hour feed field equals settlement.

Next acceptance gate: fix rollover capture, finalization tracking and capacity; deploy the corrected source with a fresh registration; capture at least two new complete markets and re-audit before evaluating strategies. Preserve the current recordings.
