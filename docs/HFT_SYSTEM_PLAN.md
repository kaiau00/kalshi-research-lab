# Kalyx HFT System Plan

## Purpose

Build and test a fast, disciplined market-making system for Kalshi BTC 15-minute
Up/Down markets. The aim is to find a repeatable, net-of-fee edge with verified
execution—not to maximize trade count or promise a return before the evidence
exists.

The system is deliberately separate from the funded directional bot. HFT work
uses its own Kalshi Demo runner, its own durable ledger, and a read-only
recorded-market replay. No HFT component currently has a production-order path.

## What “good” looks like

A candidate must demonstrate all of the following before it can be considered
for a small live pilot:

- positive P&L after Kalshi fees under a conservative queue model;
- positive P&L after one- and two-cent adverse-price stress;
- results that do not depend on the three largest winners;
- positive performance in at least four of five chronological blocks;
- at least 20 forward UTC dates and 1,000 plausible fills;
- zero unresolved inventory or reconciliation failures; and
- matching Demo evidence for quoting, cancellation, fills and inventory.

This is a high bar on purpose. A rapid series of attractive backtests without
these checks is more likely to be an execution or overfitting error than an
edge.

## System design

### 1. Deterministic execution and safety

The lowest layer owns all order lifecycle and safety decisions:

- post-only one-contract Demo quotes;
- fixed quote lifetime and cancellation handling;
- durable order journal, position reconciliation and resting-order checks;
- hard premium, inventory and unresolved-write limits; and
- explicit stop controls.

It is deterministic and auditable. An ML model may never send an order,
increase a limit, bypass a risk rule or invent a price or size.

### 2. Deterministic market-making baseline

Study 029, `deterministic_binary_market_maker_001`, is the current baseline.
It derives settlement probability from the observed BRTI path, market midpoint
and microprice information, then uses binary CARA inventory reservation values
to decide whether to post a passive YES or NO quote.

Its replay is intentionally pessimistic: 500 ms acknowledgement latency, back
of displayed queue, no cancellation credit, no block-trade credit, and a fill
only after a compatible later public trade. See
[the frozen protocol](DETERMINISTIC_HFT_BASELINE_STUDY_029_PROTOCOL.md).

### 3. ML supervisory layer

After the deterministic baseline proves a credible edge, an ML model can
estimate short-horizon fill probability, adverse-selection risk, volatility
regime and expected net value. It may only:

- veto a quote;
- restrict the allowed side to YES or NO;
- choose among preapproved quote widths, lifetimes and inventory bands; or
- take the system out of the market when calibration deteriorates.

Every model prediction, feature snapshot, decision and later result must be
recorded. Retraining occurs offline; a replacement model must beat the prior
one on untouched data before promotion. It never silently changes live rules.

### 4. Jev comparison

Jev is not the HFT engine. It is a possible supervised regime/veto input after
the baseline passes its gates. The locked comparison is:

1. deterministic baseline;
2. baseline plus Jev veto; and
3. baseline plus Jev directional filter.

Jev may only remove a deterministic action. It cannot originate a quote, set
price or size, or bypass risk. It remains disabled today.

## Evidence so far

- The separate HFT Demo service is operating with post-only one-contract
  mechanics, cancellation recovery, durable journal and reconciliation checks.
- The paired main book/BRTI tape and public-trade sidecar record the data needed
  for a conservative queue replay.
- The original 39.2-hour, three-date baseline replay had two quote intents and
  zero plausible fills. It did **not** show an edge.
- A later exploratory cached one-hour slice on October 24 had three simulated
  fills and +$0.4238 after modeled fees. That covers one settled market and is
  not evidence of profitability.
- Replay correctness now includes fractional public-trade volume and avoids
  unnecessary work on trades while no simulated quote is live. The latest
  repository test suite passed 320 tests for that change.

The honest current conclusion is: the execution/research foundation is useful,
but no HFT strategy has proven economic value yet.

## Current work

Raw paired tape is expensive to decompress and merge repeatedly. The next
component is an exact normalized replay cache: it will preserve the verified,
receipt-ordered merged events and their input hashes once, then make repeated
fixed-baseline and preregistered parameter runs fast. It is derived material;
the verified raw archives remain the source of truth.

Once it is in place, the work sequence is:

1. replay the frozen baseline over all available complete forward days;
2. publish fill, fee, P&L, stress, concentration and drawdown results;
3. if the baseline fails, reject it rather than tune toward a favorable slice;
4. if it passes initial evidence, run a small preregistered parameter study on
   development data and reserve later dates for validation;
5. run the selected version on Demo for operational confirmation; and
6. only after those gates, compare the locked Jev variants.

## Non-negotiable constraints

- No claim of impressive returns before forward data supports it.
- No HFT live order until a separately authorized pilot.
- No self-modifying live strategy or unbounded real-time ML adjustments.
- Every rejected configuration, failed fill assumption and negative result stays
  in the registry as evidence.
- Railway’s $10 hard usage limit remains in force.
