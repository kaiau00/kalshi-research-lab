# Research portfolio status

Updated on 2026-10-13 after the completed live audit, Studies 004 and 008, and the evidence-based strategy review.
This document controls attention and runtime scope; it does not delete evidence or authorize orders.

## Active development

| Work | Purpose | Runtime policy |
|---|---|---|
| Study 007 — Rollover Bridge | Test the verified prior-settlement-to-next-target handoff | Bounded, resumable replay only; no continuous Railway worker |
| Study 009 — Moderate Disagreement | Collect untouched evidence for the frozen development lead | Read-only monitor after the October 16 billing reset |
| Study 010 — Market Calibration | Test whether a conservative calibration of Kalshi's own midpoint creates executable favorite-side value | Frozen development engine and resumable replay; no order path |
| Study 011 — Jump-Robust Settlement | Test whether jump-separated realized volatility fixes the Gaussian model's overconfidence | Frozen feature audit shares Study 010's resumable replay; no order path |

## Passive completion

Studies 003, 005 and 006 remain frozen and may finish their preregistered forward windows because they share the
existing archive pipeline and add little marginal runtime cost. They receive no parameter changes or new live
authority. Study 003's `adaptive_baseline` is also a source benchmark for later comparisons.

## Archived or rejected

- `adaptive_volatility` production revision — rejected by the completed 37-fill live audit;
- `adaptive-monitored-exit-001-20261007` — rejected by the identical-entry exit counterfactual;
- `tail_underdog` and its 135/180-second variants — archived after sparse, negative demo evidence;
- Study 004 and all forty parameter configurations — completed with no winner;
- Study 008 and all three probability-pool candidates — completed and rejected;
- Study 016 Databento futures overlay — completed and rejected after the larger micro-BTC replication failed
  probability, concentration, stress and consistency gates;
- Risk Sizing Audit 001 — frozen evidence; no new observations and no selection while the signal edge is unproven;
- completed fair-value, tail and adaptive demo ledgers — preserved with their runners disabled;
- prior adaptive and Market Anchor production ledgers — immutable historical records, never reused for a new
  revision.

Archived code and reports remain in the repository. A failed strategy is evidence and must not disappear or return
under a new name.

## Production state

New real-money entries remain durably paused. The October 13 hosted audit found nine conservative fills, all nine
officially settled, zero unresolved orders and an active reconciliation/status runner. The production adapter may
be retired after a separate zero-position, zero-resting-order and ledger-completeness check; this document does not
change its runtime state.

## Deletion policy

Delete only rebuildable local material: Python bytecode, test/lint caches, temporary downloaded archives after
checksum verification and duplicate derived reports. Preserve raw receipt-ordered events, verified archives,
checkpoints, registrations, source hashes, demo and production ledgers, official outcomes, audit reports and failed
study results.

The 2026-10-13 cleanup removed local `__pycache__`, `.pytest_cache`, `.ruff_cache`, `.pyc` and `.DS_Store` files,
about 956 MB of downloaded Study 007 benchmark/sample archives, and one obsolete pre-fix checkpoint copy. The
verified object archive, frozen manifests and seeds, current resumable checkpoints, ledgers, registrations,
reports and Railway volume remain intact.
