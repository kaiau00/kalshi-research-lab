# Kalyx — complete operational handoff

**Prepared:** November 11, 2026 (America/New_York)  
**Repository:** `kaiau00/kalshi-research-lab` (public)  
**Local checkout:** `/Users/kaiau/Desktop/Kalyx`  
**Default branch:** `main`  
**Purpose:** hand the project to a new agent without losing safeguards, evidence, or the distinction between historical experiments and an authorized live system.

## 1. Executive status — read this first

There is **no proven profitable Kalshi strategy** in this repository. Several appealing historical results failed forward, stress, consistency, or drawdown checks. Do not describe any candidate as proven and do not resume trading merely because a historical simulation looks good.

All order-producing systems are deliberately inactive:

| System | Current state | Durable control | Last known exposure |
| --- | --- | --- | --- |
| Production BTC 15-minute bot | Service stopped; entries paused | `/data/production-market-shrunk-half-kelly-cap5-001/PAUSE_ENTRIES` | 0 position, 0 resting/unresolved orders |
| HFT Demo market maker | Service stopped; quoting paused | `/data/hft-demo-029/PAUSE_QUOTES` | 0 inventory, 0 active/unresolved orders |
| Research recorder / studies | Service stopped for cost control | N/A | Read-only research only when resumed |

The user explicitly asked to stop live trading and preserve the controls. **Do not remove `PAUSE_ENTRIES` or `PAUSE_QUOTES`; do not restart an order path, manually reconcile an order, move money, change sizing, or promote a strategy without fresh explicit user authorization.**

Railway compute is intentionally stopped until the billing reset because cost is near the $10 hard limit. The immediate productive work is documentation, local tests, and planning. The next bounded paid computation is the Rollover Bridge replay only after reset and user approval.

## 2. Railway state and cost guardrail

Railway project: `Kalyx` (`c6476eeb-df32-47aa-b0ef-262a50f8e9a8`)  
Production environment: `15e2863f-f700-45c7-973c-d00903bed9af`

As verified on November 11:

| Resource | ID / name | State |
| --- | --- | --- |
| Research service | `research-lab` / `a1bf43d4-6a8b-463a-9711-63a61e399688` | stopped, 0 replicas |
| HFT Demo service | `hft-demo` / `eaa351c5-87f9-4c3c-8bdc-28948ebee0c4` | stopped, 0 replicas |
| Research durable volume | `research-lab-volume` | READY; about 3.516 GB / 5 GB used |
| HFT durable volume | `hft-demo-volume` | READY; about 0.176 GB / 5 GB used |
| Archive | `research-archive` bucket | must be preserved |

Railway’s deployment display shows `FAILED` for both stopped services because they were deliberately taken down with Railway. Treat that as an intentional cost stop, **not** an application failure.

Current-period usage was **$9.5757 of the $10 hard limit**; the next reset is **November 16, 2026 at 1:17 PM EST** (`2026-11-16T18:17:14Z`). Storage continues to accrue. Do not start either service before the reset, raise the hard limit, or delete storage. The target operating rule is a hard $10 limit.

When operating Railway, use the Railway skill/CLI and preserve the existing project, variables, volumes, and bucket. Confirm the active project and service before any command. A restart is a meaningful paid action, not routine maintenance.

## 3. Secrets, accounts, and safe boundaries

* Secret names and setup expectations are in [`.env.example`](../.env.example). Never place actual API keys, private keys, passwords, dashboard tokens, or connection strings in Git, docs, logs, or chat.
* Production BTC 15-minute markets are **Kalshi Predictions** on exchange index 2, subaccount 0 — not Kalshi Perpetuals/Invest. Previous confusion about the two products caused operational mistakes; keep all account scopes explicit.
* The production and demo clients use separate credentials/configuration. Treat every requested action as scoped to a specific account, environment, ledger, and market family.
* The repository is public. Before pushing, run a secret scan and inspect the staged diff. Never add `.env`, downloaded account exports, receipts containing authentication material, or raw private keys.

## 4. Production system — historical record, not a recommendation

The most recent real-money runner was `market_shrunk_half_kelly_cap5_001` on `KXBTC15M` (BTC 15-minute Up/Down, Predictions). It is paused, not approved to resume.

Historical configuration:

* probability: 90% 60-second variance + 10% 600-second variance; then 75% raw probability + 25% Kalshi midpoint in log-odds space;
* completed-minute decisions, 5–300 seconds remaining, 500 ms delayed IOC;
* selected ask $0.45–$0.80, at least 0.005 modeled net edge after fee, raw/midpoint gap at most 0.075, spread at most $0.02, and nonnegative edge after a $0.02 adverse-price stress;
* half-Kelly from current cash, integer contracts, depth-capped, fees inside a **$5 all-in cap**;
* one attempt per market, no POST retry, hold to official settlement, no early exit/cooldown/daily stop.

Last persisted production baseline before stopping the service: **36 settled filled markets, realized net P&L -$16.2113, no position, no resting order, no unresolved order**. Its historical Study 023 backtest also failed validation drawdown and stressed-block consistency gates. It is not an edge claim.

Earlier production ledgers are historical and remain paused:

* `/data/production-market-anchor-conservative-001` — 9 settled fills, 9 attempts, realized P&L `-$0.1948`.
* `/data/production-market-anchor-001` — 38 fills, paused.
* `/data/production-adaptive-001` — 37-fill adaptive audit; early monitored exits made results worse than holding identical entries to settlement.

Before *any* future production action, independently verify durable controls, signed account positions, resting orders, ledger, market scope, current balance, and all outstanding orders. No manual order/reconciliation/money movement is authorized by this handoff.

## 5. HFT Demo — completed feasibility check, currently paused

The deterministic market-maker implementation is under `src/hft_demo/` with its dashboard/API in `src/hft_demo/app.py`. It is Kalshi **Demo only** and must stay demo-only.

Research outcome:

* Study 029 replayed 39.2045 hours / 3 days of recorded public market data (2,049,350 trades).
* It produced 2 quote intents, 1 acknowledged passive quote, **zero plausible fills**, and zero economic P&L.
* Study 030 diagnostic relaxations also produced zero plausible fills.
* Conclusion: the deterministic passive maker baseline has no credible economic edge from this evidence. Do not add Jev, ML, or a directional model to it yet. A model cannot repair a baseline with no viable fill economics.

The Demo service was restarted only long enough to resolve a historical `uncertain_cancel` record (a stale post-only NO order, HTTP 404). The final forensic check found a stored fill of zero, no listed resting order, no Demo position, and the runner wrote an acknowledged cancellation. It then returned to `quotes_paused` and was stopped. Historical Demo totals (30 orders, 2 filled contracts, 2 settlements, +$0.4200) are not statistically meaningful and must not be advertised as evidence of an HFT strategy.

Read first:

* [HFT system plan](HFT_SYSTEM_PLAN.md)
* [Study 029 protocol](DETERMINISTIC_HFT_BASELINE_STUDY_029_PROTOCOL.md)
* [Study 029 result](DETERMINISTIC_HFT_BASELINE_STUDY_029_PRELIMINARY_RESULT.md)
* [Study 030 diagnostic](HFT_FEASIBILITY_DIAGNOSTIC_030.md)
* [Demo forensic audit](HFT_DEMO_FORENSIC_AUDIT_20261107.md)
* [Jev data audit](JEV_GATED_HFT_DATA_AUDIT_028.md)

## 6. Strategy research ledger

This is the source-of-truth summary. Individual protocol/result files provide exact frozen parameters and gates.

| Study / idea | Outcome | Rule for successor agent |
| --- | --- | --- |
| 003 candidate validation | frozen read-only | preserve; no automatic promotion |
| 004 parameter search | none of 40 configs passed all gates | do not reopen as a tuning exercise |
| 005 Market Anchor | initially interesting, ultimately insufficient/failed forward support | historical only |
| 006 Conservative Market Anchor | 7-date milestone failed all gates except max drawdown | rejected |
| 008 Market Anchor improvement | complete and rejected | do not rerun/retune |
| 009 Moderate Disagreement | frozen read-only, no order path | preserve as research evidence |
| 010/011 calibration/jump robustness | development protocols only | do not deploy automatically |
| 016 Databento overlay | no production promotion | read result/protocol before use |
| 019/020/021/022/023/024/027 | sizing/frequency/parameter studies | no robust 8–12/day candidate; 023 failed validation drawdown/stress-block gates; sizing tests cannot create edge |
| 025/026 | post-hoc failure regime and holdout work | explanatory only; no valid promotion |
| 028/029/030/031 HFT/Jev | baseline has no plausible fill economics; Jev disabled | no model integration before a viable deterministic baseline |
| 032 Weather | no candidate | two-sided fixed-time sample too small; earlier horizon screen negative/unstable |
| 007 Rollover Bridge | **next bounded research lead** | replay pending; no order path |

Do not delete these historical protocols or rewrite their stated results. A negative result is valuable anti-overfitting evidence.

## 7. Weather research — closed until a valid source changes the answer

Study 032 is in `src/weather_research/` and its scripts are in `scripts/download_weather_*_032.py` and `scripts/weather_price_calibration_032.py`.

The current KXHIGHNY contracts are sourced to **The Weather Company (TWC)**. Public NWS/NOAA readings may not be substituted for the contractual source. A TWC trial application was not submitted: eligibility required a commercial entity/business email and the user did not have one. Never misrepresent identity or invent business details to obtain data.

NCEI’s Central Park daily series aligned to 91/91 older NWS-sourced contracts, which validates historical settlement alignment only—not intraday lock-in timing. Fixed 5/15/30-minute analysis yielded only two usable two-sided observations. Earlier 1/2/4/8-hour bands were negative and unstable after development/validation and adverse-price stress. There is no weather candidate to deploy.

Read:

* [Weather Study 032 protocol](WEATHER_SETTLEMENT_EDGE_STUDY_032_PROTOCOL.md)
* [Earlier-horizon calibration result](WEATHER_EARLIER_HORIZON_CALIBRATION_032.md)

## 8. Rollover Bridge Study 007 — the next credible work item

This is the most sensible remaining research direction because it uses a testable market-structure fact rather than a model-hunting claim:

> The outgoing BTC contract’s official last-minute BRTI target is the incoming 15-minute market’s strike. Test whether the observable relationship immediately after rollover contains executable predictive information after price, fees, latency, depth, and stress.

The study has **no order submission path**. It evaluates endpoint-versus-average, minute shape/velocity, and jumps 5/15/30/60 seconds after open; pools with the Kalshi midpoint; and applies actual 500 ms arrival, displayed depth, fees, stress, a $1 maximum, and one selection per market.

Frozen provenance:

* dataset ID: `e2d5cb33e7c44660809b531f03d4b4e3`
* segment range: 4345–7540 inclusive
* seed digest: `cf620d41eb95df0912d1a26ec1708d9545a821dbb3a3442647f09bab8055f786`
* terminal digest: `aab571dfb5ee829b2fe3f00a06af8ce0cd7d7494e4319ff563e7848b4f44aab4`
* scale: 3,196 segments, 591,327,720 receipt events, about 14.341 GB compressed archive; prior local runtime estimate about 2.87 hours.

The core unit tests passed 8/8 and the command-line interfaces were smoke-tested. The full replay has **not** run, so it has no performance result. The safe next action after the billing reset and the user’s explicit approval is the bounded procedure in [the reset runbook](ROLLOVER_BRIDGE_RESET_RUNBOOK.md): start only `research-lab`, run batches of at most 100 segments, inspect the generated JSON and Railway cost after every batch, and stop on anomalies or budget pressure. Do not start HFT Demo or production as part of this.

Key implementation paths:

* `src/rollover_bridge/`
* `scripts/run_rollover_study.py`
* `scripts/run_rollover_local.py`
* `scripts/audit_rollover_sample.py`
* `scripts/analyze_rollover_development.py`
* [Study 007 protocol](ROLLOVER_BRIDGE_STUDY_007_PROTOCOL.md)
* [100-segment benchmark](validation/rollover-bridge-100-segment-benchmark.json)

## 9. Data architecture and integrity

The high-volume recorder/archive is durable and must be retained:

* Segment catalog: `/data/segments-v6`; last reported catalog: 9,969 segments, 2,226,588,512 receipt events replayed, 4,112 markets.
* Normalizer: `/data/normalizer-v2`, approximately 1.9 GB.
* HFT trade cache: approximately 7.9 MB.
* The full sealed archive lives in the `research-archive` bucket; it is not all available locally.

Recorded data is valuable because minute OHLCV alone cannot reproduce actual Kalshi two-sided prices, best-level depth, quote timing, arrival behavior, fees, and settlement. Treat historical simulation as executable only if it models those details; otherwise label it as a research screen, not a backtest.

Preserve archive continuity and segment digests. If restarting recording later, first verify bucket/volume health, no growing sealed backlog, no duplicate segments, and normalizer checkpoint continuity.

## 10. Recommended reading order for a new agent

1. This handoff.
2. `README.md`, `.env.example`, `Dockerfile`, `railway.toml`, and `pyproject.toml`/requirements files.
3. [Rollover reset runbook](ROLLOVER_BRIDGE_RESET_RUNBOOK.md) and [Study 007 protocol](ROLLOVER_BRIDGE_STUDY_007_PROTOCOL.md).
4. [HFT plan](HFT_SYSTEM_PLAN.md), Study 029 result, Study 030 diagnostic, and HFT forensic audit.
5. [Study 023-related sizing/frequency results](HISTORICAL_FREQUENCY_STRATEGY_STUDY_021_RESULT.md), [Market confirmation](HISTORICAL_MARKET_CONFIRMATION_STUDY_022_RESULT.md), and [cap expansion](MARKET_SHRUNK_EXPANDED_KELLY_CAP_STUDY_027_RESULT.md).
6. Weather Study 032 documents only if reopening weather research with a contract-valid real-time TWC source.
7. Inspect durable status and raw reports before making any claim about a runner.

## 11. Tests and review checks

Run relevant tests before changing code. The exact test selection should follow the files changed; common checks include:

```bash
cd /Users/kaiau/Desktop/Kalyx
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_rollover_bridge.py
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_weather_calibration.py
```

Before a deployment, inspect `git status`, review the diff, verify the current Railway project/environment/service, and confirm no secrets are staged. Before any order-capable restart, require fresh user authorization and run a full account/ledger/control reconciliation.

## 12. Non-negotiable operating rules

* Never imply a backtest proves profitability or scale a strategy automatically.
* Keep the $10 Railway hard limit; do not increase it without the user explicitly authorizing the expense.
* Do not delete archive buckets/volumes to control cost without separate approval; they contain the scarce historical evidence.
* Do not enable Jev/AI because it sounds sophisticated. It only belongs in a preregistered comparison after a deterministic strategy has a credible executable baseline: baseline alone, baseline + veto, baseline + directional filter. Cache all outputs and charge inference costs to the study.
* Treat every account/action scope separately: production vs demo; Predictions vs Perpetuals; BTC 15-minute vs another series; and a named durable ledger.
* Preserve frozen protocols and rejected results. Any new hypothesis needs its own protocol, fixed gates, chronology-safe development/validation split, adverse-price/fee/depth treatment, and no live-order path until it earns a prospective test.
* The user’s objective is a live profitable strategy, but the correct near-term objective is preventing further unverified loss while efficiently falsifying or validating hypotheses.

## 13. First actions after taking over

1. Do **not** start anything before the November 16 billing reset.
2. At reset, confirm usage is below $1, both durable volumes/bucket are healthy, `PAUSE_ENTRIES` and `PAUSE_QUOTES` still exist, and no exchange/ledger exposure exists.
3. Ask the user for explicit permission and a batch-cost budget before starting only `research-lab` for the bounded Rollover 007 replay.
4. Process no more than 100 segments per batch; inspect results and usage after each batch. Do not parameter-tune midstream.
5. If the rollover result shows an apparent edge, hold a fixed untouched test block and paper/prospective phase before any demo or production integration.
6. If it fails, record the negative result, stop compute, and return to idea generation—do not force a live bot from rejected work.

## 14. What the user needs to know, plainly

The project has good infrastructure and unusually valuable market microstructure data, but it does not currently have a verified trading edge. Production and demo execution are safely paused. The remaining high-value work is a cost-bounded, preregistered replay of Rollover Bridge Study 007, not another parameter sweep or an AI overlay. This is the clearest path to learning something real without compounding unproven losses.
