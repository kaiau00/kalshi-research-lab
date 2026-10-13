# Rollover Bridge Study 007 protocol

Registered on 2026-10-12 before inspecting Rollover Bridge P&L. This study is read-only and cannot submit an
exchange order. It does not change the live conservative Market Anchor strategy.

## Question

Does information created by the mechanical handoff between consecutive KXBTC15M contracts improve probability
forecasts and executable returns beyond the contemporaneous Kalshi market probability?

The next market's target is the previous market's official final-minute BRTI average. Study 007 measures the
endpoint-versus-average gap, the shape and velocity of that prior minute, and jump-separated trailing variance.
It produces a causal structural probability for the next contract's official outcome.

## Frozen development source

- Dataset: `e2d5cb33e7c44660809b531f03d4b4e3`
- Seed: the verified v6 comparison checkpoint immediately before segment 4,345
- Development segments: 4,345 through 7,540 inclusive
- Terminal segment digest: `aab571dfb5ee829b2fe3f00a06af8ce0cd7d7494e4319ff563e7848b4f44aab4`
- Terminal archive SHA-256: `07d270bf3e5bdfd7690c26ac7ed20fe8a8a5d13b2b136315ddd3b38fc82f33`

All results from this source are development evidence. They are not an untouched holdout, even if a date or block
was not used to fit a particular model.

## Pre-P&L scaling amendment — 2026-10-12

Before inspecting any Rollover Bridge probability, trade selection or P&L result, the bounded replay exposed an
algorithmic scaling defect: every receipt event scanned every historical decision row for pending arrivals and a
finalized market scanned rows belonging to all markets. The implementation now maintains a due-time heap for
pending arrivals and a per-ticker row index for settlements. Both indexes are derived from the same persisted rows
and are rebuilt after checkpoint restoration. Strategy inputs, forecast math, offsets, latency, book-age rules,
execution assumptions and development split are unchanged.

The original eight-segment report was reproduced byte for byte after this change. A separate 100-segment timing
run covered segments 7,441–7,540 and 50,000,000 events without inspecting strategy P&L. It completed in 834.25
seconds on the local machine, produced 102 usable openings from 104 observed markets at every registered offset,
and found zero gaps, malformed events or clock adjustments. The frozen full manifest contains 3,196 segments,
591,327,720 events and 14.341 GB of compressed archives. The measured projection is about 2.87 hours.

The amended runner downloads and verifies one archive at a time, checkpoints every ten segments and at every clean
shutdown, removes the temporary archive after processing, and resumes only when the registration, manifest and
checkpoint hashes match. The first two segments were replayed solely to verify checkpoint/resume behavior; the
saved checkpoint is at segment 4,347 with 200,000 events and no P&L report has been generated.

- Original source SHA-256: `4330f7104950f2f02988e203ce9868ba4fc1be2408a97fb525ab8f485b18b1da`
- Original registration SHA-256: `2490545e46fb015097f58303ed36875c3dc9727ec9c2372c58d8ca61e3d84132`
- Amended source SHA-256: `9cc7d560078892cb157080a02d222c3b59d5d59c67f9503193366209510df1bd`
- Amended registration SHA-256: `cbc182ee76f8ffc804efc8c8b1a8504460d01011f08bda91a9e32f0b6b6cada2`
- Frozen manifest SHA-256: `ec9d3f4cfc38e44d4f59418f1fe0c858efef38bbb8d6b90aab399098c0620357`

This amendment supersedes the original code registration for Study 007 before Phase 2 results are inspected. It
does not change the frozen data range or authorize an order.

## Phase 1: data and decision tape

Before calculating strategy P&L, audit opening coverage at 5, 15, 30 and 60 seconds after each market opens. A
usable row requires 600 consecutive one-second BRTI observations, all 60 observations from the prior target minute,
a fresh two-sided Kalshi book, and the first recorded book at or after a 500 ms modeled arrival. Missing inputs stay
missing. The tape records both sides, displayed best-level depth, receipt timing and the eventual official result.

The first structural forecast uses only observations received by the decision timestamp. It estimates continuous
variance with bipower variation, isolates excess realized jump variation, filters a mean-reverting one-second log
velocity with a fixed 30-second half-life, and propagates the final 60-second arithmetic average. This first model
is a diagnostic baseline, not a production candidate.

## Phase 2: development and candidate freeze

Compare the structural forecast with the Kalshi midpoint using prequential log loss and Brier score. Any probability
pool must treat the market log-odds as its prior and shrink new feature coefficients toward zero. Development may
choose one sampling offset and one fixed model, but every tried specification and its result must be reported.

The first registered development model pools all four offsets. It uses the Kalshi midpoint log-odds as a fixed
offset and fits adjustments for the volatility-scaled rollover gap, volatility-scaled prior-minute velocity,
volatility-scaled filtered velocity, jump share, the structural-versus-market log-odds difference and three
sampling-offset indicators. Fit a logistic model with an L2 penalty of 10 on the first 60% of observed UTC dates
and evaluate on the remaining 40%. This chronological split is a development diagnostic, not an untouched holdout.
It requires at least 50 usable training rows. The strategy checks registered offsets in chronological order and
permits only the first qualifying fill per market.

Executable simulation uses the recorded quote at the first receipt event at or after 500 ms, displayed best-level
integer depth, IOC execution, exact supported Kalshi fees, a fixed $1 all-in maximum, and one filled entry per market.
The model must show at least four percentage points of net edge after adding two cents to the arrival ask and
applying the fee. No resting fill, midpoint fill, backfilled book, or result-derived feature is allowed.

## Phase 3: prospective gate

After development, freeze a separate candidate registration and begin at a new segment boundary. Promotion review
requires at least 20 untouched UTC dates and 100 officially settled simulated fills, positive net P&L, positive P&L
after removing the three largest winners, positive one-cent and two-cent adverse-price stress, more than half of UTC
days positive, positive results in four of five chronological blocks, better prequential log loss than the Kalshi
midpoint, acceptable calibration, and no unresolved exposure. Also report 1-second and 2-second latency stress.

Passing these gates authorizes only a review. It does not authorize demo or production orders.
