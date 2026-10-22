# Strategy registry

This is the canonical inventory of strategy ideas, implemented variants, execution overlays and sizing rules in
this repository. A name appearing here means only that it has been considered or implemented. It does not mean the
strategy has an edge or is authorized to trade.

Statuses have precise meanings:

- **benchmark**: implemented to measure other ideas, not promoted;
- **rejected**: the relevant completed evidence failed its declared screen;
- **prospective**: frozen and collecting future read-only evidence;
- **development**: may be explored on disclosed data but has no untouched result;
- **concept**: a mathematical proposal that is not yet implemented;
- **historical live**: once sent orders under explicit authorization; the ledger is preserved;
- **active live**: the selected production adapter may submit orders under its frozen authorization;
- **paused live**: the production adapter exists but new entries are durably paused.

No read-only study, registry entry or favorable result grants order authority. The user-authorized
`market_shrunk_half_kelly_001` production runner is selected and active with $140.0000 of authorized Predictions
funding. The earlier conservative ledger remains immutable and paused.

## Directional strategies and research candidates

| ID | Mechanism | Evidence and disposition | Implementation or specification |
|---|---|---|---|
| `basic_fair_value` | Gaussian probability for the final 60-second BRTI arithmetic average versus the executable ask and fee | Benchmark. Demo made $32.5630 on 132 settlements, but demo liquidity did not transfer reliably to production | `src/research_lab/engine.py`, [initial definitions](STRATEGIES.md) |
| `tail_underdog` | Same probability model, restricted to the cheaper side at no more than $0.35, within one modeled standard deviation and late in the market | Rejected as an edge. Demo lost $0.7094 on 10 settlements; only five 135-second and six 180-second shadow signals were observed | `src/research_lab/engine.py`, [demo audit](DEMO_EXECUTION.md) |
| `tail_control_135s` | Signal-only copy of `tail_underdog` with a 135-second maximum | Completed frequency diagnostic; five signals, no promotion test | `src/demo_execution/runner.py`, [demo audit](DEMO_EXECUTION.md) |
| `tail_window_180s` | Same tail rule with a 180-second maximum | Completed frequency diagnostic; six signals, no promotion test | `src/demo_execution/runner.py`, [demo audit](DEMO_EXECUTION.md) |
| `adaptive_volatility` | Gaussian settlement model with one-second variance blended 70% from 60 seconds and 30% from 600 seconds | Rejected for production. The 37-fill live audit lost $37.0860; identical-entry hold-to-settlement lost $25.0750 while the model expected +$24.7023 | `src/research_lab/engine.py`, [live audit](PRODUCTION_LIVE_AUDIT_001.md) |
| `adaptive_baseline` | Study 003 copy of `adaptive_volatility` with $1 simulated risk | Prospective benchmark, not an independent strategy | `src/candidate_study/engine.py`, [Study 003](CANDIDATE_STUDY_003_PROTOCOL.md) |
| `adaptive_market_blend` | 50/50 log-odds pool of the adaptive model and Kalshi midpoint | Prospective Study 003 candidate | `src/candidate_study/engine.py`, [Study 003](CANDIDATE_STUDY_003_PROTOCOL.md) |
| `adaptive_calibrated` | Temperature-scaled adaptive log-odds; coefficient `0.7459916645763038` fixed on development data | Prospective Study 003 candidate | `src/candidate_study/engine.py`, [Study 003](CANDIDATE_STUDY_003_PROTOCOL.md) |
| `adaptive_calibrated_guarded` | Calibrated model plus spread, two-cent stress, depth and two-observation persistence guards | Prospective Study 003 candidate | `src/candidate_study/engine.py`, [Study 003](CANDIDATE_STUDY_003_PROTOCOL.md) |
| Study 004 parameter matrix | Forty fixed combinations of raw/calibrated/market-blended probabilities, edge gates, time windows, spread caps and persistence | Rejected. Zero of 40 passed all gates; zero remained positive after removing three largest winners | `src/walk_forward_study/engine.py`, [results](PARAMETER_STUDY_004_RESULTS.md) |
| `market_agreement_band_001` | Accept adaptive signals only at $0.30-$0.95, raw/market gap at most 0.08 and spread at most $0.02 | Study 005 prospective research continues. Historical live pilot was later replaced and its ledger is paused | `src/market_anchor_study`, [Study 005](MARKET_ANCHOR_STUDY_005_PROTOCOL.md), [live pilot](MARKET_ANCHOR_LIVE_PILOT_001.md) |
| `market_anchor_conservative_001` | Tighter $0.30-$0.85 price, 0.06 agreement and $0.01 spread filters; edge survives +$0.02; cooldown and loss stops | Study 006 prospective research. Real-money adapter is **paused live** after nine fills | `src/conservative_anchor`, [Study 006](CONSERVATIVE_MARKET_ANCHOR_STUDY_006_PROTOCOL.md) |
| Rollover Bridge diagnostic | Uses the exact prior-contract settlement average as the new strike, plus rollover gap, prior-minute velocity and jump-separated variance | Development Study 007. The handoff was exact in 1,893 archived adjacent pairs; profitability has not been established | `src/rollover_bridge`, [Study 007](ROLLOVER_BRIDGE_STUDY_007_PROTOCOL.md) |
| Study 008 exact control | Reproduces `market_anchor_conservative_001` on the frozen development source | Development control: 17 trades, +$0.1627 headline, -$0.5578 without top three and negative at two-cent stress | `src/market_anchor_improvement`, [result](MARKET_ANCHOR_IMPROVEMENT_STUDY_008_RESULT.md) |
| `pooled_lcb_001` | Kalshi log-odds prior plus shrinkage adjustment from raw-model disagreement; require a one-sided probability lower bound | Rejected. Selected zero trades | `src/market_anchor_improvement`, [Study 008](MARKET_ANCHOR_IMPROVEMENT_STUDY_008_PROTOCOL.md) |
| `pooled_lcb_price80_001` | Same lower-bound pool with ask below $0.80 | Rejected. Selected zero trades | `src/market_anchor_improvement`, [Study 008](MARKET_ANCHOR_IMPROVEMENT_STUDY_008_PROTOCOL.md) |
| `pooled_lcb_price80_vol90_001` | Same pool plus a 90th-percentile model-volatility veto | Rejected. Selected zero trades | `src/market_anchor_improvement`, [Study 008 result](MARKET_ANCHOR_IMPROVEMENT_STUDY_008_RESULT.md) |
| `moderate_disagreement_band_001` | Accept source signals at $0.30-$0.50 only when raw/market disagreement is greater than 0.06 and at most 0.08, with one-cent spread and two-cent stress gates | Prospective Study 009. Its favorable 45-trade development slice is data-mined and is not validation | `src/moderate_disagreement`, [Study 009](MODERATE_DISAGREEMENT_STUDY_009_PROTOCOL.md) |
| `market_beta_calibrated_favorite_010` | Expanding-window beta calibration of the Kalshi midpoint, with time-to-close strata and a lower confidence bound over executable cost | Development protocol, causal tape, calibration engine and resumable runner implemented; full frozen replay pending; no P&L yet | [Study 010](MARKET_CALIBRATION_STUDY_010_PROTOCOL.md) |
| `jump_robust_har_settlement_011` | HAR realized variance, signed semivariance and bipower jump separation feeding Student-t path simulation of the exact settlement average | Causal gap-sensitive feature audit and shared runner implemented; HAR fit and path simulation remain separately frozen work; no P&L yet | [Study 011](JUMP_ROBUST_SETTLEMENT_STUDY_011_PROTOCOL.md) |
| `quote_innovation_error_correction_012` | Model the raw-versus-market log-odds gap as a decaying state and trade only persistent innovations that survive arrival and stress | New concept. The only supporting repo evidence is the data-mined Study 009 slice | [evidence memo](EVIDENCE_BASED_STRATEGY_RESEARCH_2026-10-13.md) |
| `order_flow_execution_overlay_013` | Multi-level order-flow imbalance and microprice predict the executable ask at modeled arrival | New concept; execution overlay only. It cannot supply settlement probability | [evidence memo](EVIDENCE_BASED_STRATEGY_RESEARCH_2026-10-13.md) |
| `brti_shadow_index_014` | Reconstruct the official index from synchronized constituent books and forecast the next official BRTI observations | Concept with high information value but blocked on new licensed/synchronized constituent data | [advanced memo](ADVANCED_STRATEGY_RESEARCH.md), [evidence memo](EVIDENCE_BASED_STRATEGY_RESEARCH_2026-10-13.md) |
| `complement_parity_monitor_015` | Look for simultaneously executable YES and NO asks whose total cost plus fees is below $1 | Audit concept, not a directional model. Kalshi's complementary book representation may make valid opportunities impossible; it must first prove independent executable depth | [evidence memo](EVIDENCE_BASED_STRATEGY_RESEARCH_2026-10-13.md) |
| `databento_futures_overlay_016` | Penalized day-ahead calibration of the adaptive selected-side probability plus causal CME BTC momentum and realized-volatility features | Rejected by Study 016. The main-contract slice was only 33 trades/one day; the 166-trade micro-BTC replication made calibration worse and failed concentration, stress and consistency gates | [protocol](DATABENTO_FUTURES_OVERLAY_STUDY_016_PROTOCOL.md), [result](DATABENTO_FUTURES_OVERLAY_STUDY_016_RESULT.md) |
| `historical_candle_strategy_screen_018` | Fixed comparison of six existing strategies on audited Kalshi minute quotes and official BRTI, with chronological development/validation and a sealed holdout | Complete on development and validation; no strategy passed. The holdout remains sealed. Candle quotes cannot prove a 500 ms IOC fill | [protocol](HISTORICAL_CANDLE_SCREEN_018_PROTOCOL.md), [result](HISTORICAL_CANDLE_SCREEN_018_RESULT.md) |
| `historical_parameter_kelly_study_019` | Preregistered 1,620-configuration conservative-anchor grid with a separate $100 fixed-versus-fractional-Kelly sizing comparison | Complete. Two neighboring fixed-$1 signals passed the aggregate research gate; the later split failed two-cent stress, daily uncertainty includes zero, and the newest 20% remains sealed | [protocol](HISTORICAL_PARAMETER_KELLY_STUDY_019_PROTOCOL.md), [result](HISTORICAL_PARAMETER_KELLY_STUDY_019_RESULT.md) |
| `historical_robust_parameter_risk_study_020` | Preregistered 4,608-cell neighborhood search across volatility blend, probability blend, edge, price, disagreement, timing and spread, with risk secondary to fixed-$1 robustness | Complete with no winner. The best stressed near miss made +$24.4806 and +$9.2233 at two-cent stress but was positive in only three of five stressed blocks; no risk path was opened and the holdout remains sealed | [protocol](HISTORICAL_ROBUST_PARAMETER_RISK_STUDY_020_PROTOCOL.md), [result](HISTORICAL_ROBUST_PARAMETER_RISK_STUDY_020_RESULT.md) |
| `market_shrunk_half_kelly_001` | Study 023 signal with half-Kelly sizing capped at $3 | Historical live revision preserved at 12 settled fills and +$9.4733 realized net P&L before the authorized cap change | `src/market_shrunk_production`, [production specification](MARKET_SHRUNK_HALF_KELLY_PRODUCTION_001.md) |
| `market_shrunk_half_kelly_cap5_001` | Identical Study 023 signal with half-Kelly sizing capped at $5 | User-authorized live risk pilot using a fresh paused ledger; Study 027 found stronger stressed P&L with materially larger historical drawdown, and the signal remains unproven | `src/market_shrunk_cap5_production`, [production specification](MARKET_SHRUNK_HALF_KELLY_CAP5_PRODUCTION_001.md), [risk result](MARKET_SHRUNK_EXPANDED_KELLY_CAP_STUDY_027_RESULT.md) |
| Study 025 regime diagnostic | Predefined side, price, timing, volatility-ratio and model/market buckets applied to Study 023's exact fixed-$1 ledger | Complete diagnostic. Three overlapping buckets were stressed losers in both partitions. Avoiding 65–69-cent entries is a post-hoc candidate only; no rule changed and the holdout remains sealed | [protocol](MARKET_SHRUNK_REGIME_FAILURE_ANALYSIS_025_PROTOCOL.md), [result](MARKET_SHRUNK_REGIME_FAILURE_ANALYSIS_025_RESULT.md) |
| `market_shrunk_skip_65_69_026` | Study 023's exact first signal, but discard the entire market when its selected ask is at least $0.65 and below $0.70 | Frozen holdout candidate selected from Study 025. The newest 20% remains sealed; no demo or production authority | [Study 026 protocol](MARKET_SHRUNK_PRICE_BAND_HOLDOUT_026_PROTOCOL.md) |

The earlier advanced-research names **Jump-Robust Settlement Filter**, **Hawkes Reaction-Delay Overlay** and
**Robust Probability Pool and Evidence Gate** are preserved as the parent concepts of IDs 011, 013 and the
Study 008 framework. They are not additional independent strategies. The original integrated-OU/particle-filter
Rollover Bridge proposal is the parent concept of Study 007.

## Study 004's forty named variants

These are all rejected together by the completed Study 004 screen. Naming grammar is part of the specification:
`signal` changes probability transform and edge; `window` changes entry time; `spread` adds a spread cap; and
`persist` also requires two consecutive qualifying observations.

```text
signal_raw_e04                 signal_raw_e06                 signal_raw_e08
signal_raw_e10                 signal_calibrated_e04          signal_calibrated_e06
signal_calibrated_e08          signal_calibrated_e10          signal_blend25_e04
signal_blend25_e06             signal_blend25_e08             signal_blend25_e10
signal_blend50_e04             signal_blend50_e06             signal_blend50_e08
signal_blend50_e10             signal_blend75_e04             signal_blend75_e06
signal_blend75_e08             signal_blend75_e10             window_raw_e06_30_120
window_raw_e06_30_180          window_calibrated_e06_30_120   window_calibrated_e06_30_180
window_blend25_e06_30_120      window_blend25_e06_30_180      window_blend50_e06_30_120
window_blend50_e06_30_180      window_blend75_e06_30_120      window_blend75_e06_30_180
spread_calibrated_e06_30_180_s03  spread_calibrated_e06_30_180_s05
spread_blend50_e06_30_180_s03     spread_blend50_e06_30_180_s05
persist_calibrated_e06_30_180_s03 persist_calibrated_e06_30_180_s05
persist_calibrated_e06_30_180_s07 persist_blend50_e06_30_180_s03
persist_blend50_e06_30_180_s05    persist_blend50_e06_30_180_s07
```

## Position management and execution overlays

These change realized P&L or fill quality but do not create directional edge.

| ID | Rule | Evidence and status |
|---|---|---|
| `adaptive-monitored-exit-001-20261007` | Once-per-second position verification; reduce-only IOC exit for profit, market-over-model value or model invalidation | Historical live revision. Across the completed audit, monitored exits reduced P&L by $12.0110 versus holding identical entries. Rejected as the default |
| `adaptive-hold-settlement-002-20261008` | Verify exposure and hold until official settlement | Historical live policy and current policy for all Market Anchor revisions |
| 500 ms delayed IOC | Observe the first recorded executable book at or after modeled arrival; cap quantity to best-level integer depth | Shared research execution benchmark |
| Hawkes reaction-delay overlay | Mutually exciting book-event intensities choose trade-now, wait or reject | Parent research concept for `order_flow_execution_overlay_013`; not implemented |

## Sizing and risk policies

Sizing cannot turn a negative-expectation signal positive. These variants compare risk conditional on an entry.

| ID | Rule | Status |
|---|---|---|
| `fixed_1` | Maximum $1 all-in cost | Frozen sizing audit variant; used by Market Anchor pilots |
| `fixed_3` | Maximum $3 all-in cost | Frozen sizing audit variant; historical adaptive demo cap |
| `eighth_kelly_cap_3` | One-eighth of model Kelly, maximum $3 | Frozen audit variant |
| `quarter_kelly_cap_3` | One-quarter Kelly, maximum $3 | Frozen audit variant |
| `half_kelly_cap_3` | One-half Kelly, maximum $3 | Study 024 diagnostic and active user-authorized `market_shrunk_half_kelly_001` production risk rule |
| `quarter_kelly_cap_4/5/6` | One-quarter Kelly, maximum $4, $5 or $6 | Study 027 diagnostic. Every larger cap had worse stressed P&L and drawdown than quarter Kelly capped at $3 |
| `half_kelly_cap_4` | One-half Kelly, maximum $4 | Study 027's best stress-to-drawdown ratio among expanded paths; historical drawdown $33.3021; research only |
| `half_kelly_cap_5` | One-half Kelly, maximum $5 | Study 027's highest two-cent-stressed P&L and 4/5 positive stressed blocks; historical drawdown $38.6751; research only |
| `half_kelly_cap_6` | One-half Kelly, maximum $6 | Study 027's highest headline P&L but lower stress P&L than $5 and $52.9143 drawdown; rejected as dominated under stress |
| Conservative Anchor risk layer | One-hour cooldown; daily halt at -$2 or three settled losses; indefinite halt at $5 realized drawdown | Implemented in the paused production revision and Studies 006/008/009 |

Full Kelly for a binary contract with all-in unit cost `c` and estimated win probability `p` is
`max(0, (p-c)/(1-c))`. The audit applies the named fraction, a $100 reference bankroll, integer contracts,
displayed depth and the $3 cap. See [Risk Sizing Audit 001](RISK_SIZING_AUDIT_001_PROTOCOL.md).

## Ideas deliberately excluded or demoted

- A standalone cheap-tail buyer is contradicted by our demo result and by broad favorite-longshot evidence.
- Kelly sizing is not a source of edge and is unsafe when probability estimates are overconfident.
- Early exits are demoted after the completed identical-entry audit showed they hurt aggregate P&L.
- A Hawkes or order-flow signal is not allowed to masquerade as settlement alpha; it must be scored on future
  executable quote quality.
- Deep neural networks, reinforcement learning and an external AI signal such as Jev remain excluded until there
  are enough independent days and a fixed low-dimensional baseline they can beat out of sample.
- A constituent-index replica cannot be backfilled from Coinbase alone and called BRTI.

## Maintenance rule

Every new strategy, ablation, execution overlay or sizing rule must be added here in the same commit that introduces
its code or protocol. Record its exact ID, formula or decision rule, data requirement, evidence phase, order
authority and final disposition. Failed ideas remain in the registry.
