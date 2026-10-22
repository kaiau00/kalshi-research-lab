# Research portfolio status

Updated on 2026-10-21 after Market-Shrunk Regime Failure Analysis 025.
This document controls attention and runtime scope; it does not delete evidence or authorize orders.

## Active development

| Work | Purpose | Runtime policy |
|---|---|---|
| Study 007 — Rollover Bridge | Test the verified prior-settlement-to-next-target handoff | Bounded, resumable replay only; no continuous Railway worker |
| Study 009 — Moderate Disagreement | Collect untouched evidence for the frozen development lead | Read-only monitor after the October 16 billing reset |
| Study 010 — Market Calibration | Test whether a conservative calibration of Kalshi's own midpoint creates executable favorite-side value | Frozen development engine and resumable replay; no order path |
| Study 011 — Jump-Robust Settlement | Test whether jump-separated realized volatility fixes the Gaussian model's overconfidence | Frozen feature audit shares Study 010's resumable replay; no order path |
| Study 026 — Price-Band Holdout | One-time test of Study 025's frozen 65–69-cent exclusion | Registered and locked; explicit holdout disclosure required; no order path |

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
- Study 020 robust parameter and risk search — completed with no winner; its +$24.4806 fixed-$1 near miss failed
  the preregistered two-cent-stressed block-consistency gate, so risk comparison and holdout remained unopened;
- Study 021 frequency strategy search — completed with no winner across 11,520 cells. The only 8–12-trade/day,
  65%-win, 45–72-cent-mean-price cell with positive two-cent stress retained only +$0.3421, drew down $17.7168 and
  lost in two of five chronological periods. Validation, risk sizing and the holdout stayed closed;
- Study 022 market-confirmation search — completed with no 8–12-trade/day winner across 11,664 cells. No target-
  frequency cell survived two-cent stress. A 5.33-trade/day fallback passed every other development gate and is
  eligible only for one separately frozen lower-frequency validation diagnostic;
- Study 023 market-shrunk fallback validation — rejected. It averaged 5.70 trades/day across the unsealed 80%,
  won 71.00%, made $29.6609 and retained $12.1890 under two-cent stress, but validation drawdown missed its cap by
  $0.1635 and only three of five combined stressed blocks were positive. Risk sizing and holdout stayed closed;
- Study 024 Kelly risk diagnostic — completed after the user requested a sizing comparison on the rejected Study
  023 lead. Fixed $1 was the risk-adjusted leader. Half Kelly made +$106.6278 but hit the $3 cap on 829 of 838
  decisions and drew down $27.0156; eighth Kelly made less than fixed $1 and nearly doubled drawdown; smaller
  fractions skipped most or all trades. The diagnostic did not rescue the signal or open the holdout;
- Study 025 regime failure analysis — completed on the exact Study 023 ledger. The 65–69-cent entry band, a
  fast/slow variance ratio below 0.50 and 06:00–11:59 UTC each lost under two-cent stress in both development and
  validation, but the groups overlap. Avoiding only 65–69-cent entries is the simplest post-hoc candidate; it is
  not validated and the holdout remains sealed;
- Study 027 expanded Kelly-cap diagnostic — completed on Study 023's same 838 decisions. Quarter-Kelly robustness
  worsened above $3. Half Kelly improved through a $5 cap, but historical drawdown rose to $33.30 at $4 and $38.68
  at $5; the $6 cap was dominated under stress and drew down $52.91. No live cap changed;
- Risk Sizing Audit 001 — frozen evidence; no new observations and no selection while the signal edge is unproven;
- completed fair-value, tail and adaptive demo ledgers — preserved with their runners disabled;
- prior adaptive and Market Anchor production ledgers — immutable historical records, never reused for a new
  revision.

Archived code and reports remain in the repository. A failed strategy is evidence and must not disappear or return
under a new name.

## Production state

The user-authorized `market_shrunk_half_kelly_001` runner is selected and active on Railway with a fresh durable
ledger. It began with exactly $140.0000 of internally routed Predictions cash, zero attempts, zero fills, no
position, no resting order and zero unresolved orders under funding revision
`market-shrunk-half-kelly-funding-002-20261019`. The previous conservative ledger remains preserved and paused at
nine officially settled fills and -$0.1948 realized net P&L. Before the first bot order, a later Kalshi internal
transfer reduced BTC-path cash to $129.9915. The user explicitly authorized resumption at that balance; the durable
commissioning receipt prevents the already-passed $140 preflight from being repeated after ordinary cash changes.

## Deletion policy

Delete only rebuildable local material: Python bytecode, test/lint caches, temporary downloaded archives after
checksum verification and duplicate derived reports. Preserve raw receipt-ordered events, verified archives,
checkpoints, registrations, source hashes, demo and production ledgers, official outcomes, audit reports and failed
study results.

The 2026-10-13 cleanup removed local `__pycache__`, `.pytest_cache`, `.ruff_cache`, `.pyc` and `.DS_Store` files,
about 956 MB of downloaded Study 007 benchmark/sample archives, and one obsolete pre-fix checkpoint copy. The
verified object archive, frozen manifests and seeds, current resumable checkpoints, ledgers, registrations,
reports and Railway volume remain intact.
