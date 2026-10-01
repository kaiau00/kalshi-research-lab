# Candidate study 003 protocol

Declared on September 30, 2026 before any candidate consumed post-comparison events. The development evidence is frozen v6 comparison `v6-002`, ending at archived segment 4,344 and receipt time `2026-09-30T01:30:55.033974Z`. Candidate evaluation begins with segment 4,345. Earlier data may initialize market state and fit the declared calibration transform, but cannot contribute candidate P&L.

## Objective

Test whether adaptive volatility can be made less overconfident, less dependent on rare winners and more robust to executable prices. The existing adaptive Kalshi demo configuration remains unchanged. These candidates are signal-only simulated accounts and have no order-submission path.

## Fixed shared assumptions

- BTC `KXBTC15M` only.
- Independent $100 account per candidate; maximum $1 modeled cost per market.
- Existing 5–300 second entry window, 4% minimum modeled net edge, fee model, freshness requirements, official-outcome settlement and 500 ms delayed IOC simulation.
- Receipt-order processing from verified archived v6 segments only.
- Maximum three IOC attempts ten seconds apart and no reentry after any fill.
- No maker fills, intramarket exits, invented outcomes or favorable handling of missing data.

## Candidates

1. `adaptive_baseline`: the registered adaptive-volatility forecast and decision rules unchanged.
2. `adaptive_market_blend`: a 50/50 blend in log-odds space between the adaptive forecast and the executable market midpoint. The YES midpoint is halfway between the best YES ask and the implied YES bid `1 - best NO ask`.
3. `adaptive_calibrated`: symmetric temperature scaling of the adaptive probability. A single positive coefficient is fitted once on the 616 settled adaptive trades in `v6-002` by minimizing binary log loss with an L2 penalty of 1 around coefficient 1. The input is the selected-side probability and label is whether that side won. The coefficient is recorded in the study registration before post-cutoff replay starts.
4. `adaptive_calibrated_guarded`: candidate 3 plus all of these fixed execution guards:
   - quoted binary spread `YES ask + NO ask - 1` no greater than $0.06;
   - modeled edge remains at least 4% after adding $0.02 adverse price slippage and recomputing the fee;
   - best-level displayed depth is at least twice the requested integer quantity;
   - the same side qualifies in two consecutive one-second evaluations, with its ask changing by no more than $0.01.

## Evaluation and promotion gate

Do not tune these definitions from their forward results. Review only after at least 20 post-cutoff UTC dates and at least 100 settled markets for a candidate. A candidate must have positive P&L after fees, positive P&L after removing its three largest winners, positive daily P&L on more than half of observed dates, maximum cost-basis drawdown no greater than $20, and better calibration than the unchanged baseline. It must also survive separate one- and two-cent adverse-slippage reports.

Passing these gates permits a later untouched validation experiment; it does not authorize production orders or establish a durable edge. Jev is excluded from this study. It may be tested later as a fifth shadow veto only after these deterministic and statistical controls establish a comparison baseline.

## Persistence

The study registration, source hash, frozen seed identity, calibration coefficient, segment cursor, exact simulator state and derived reports must be durable under `/data/candidate-studies/003`. A registration or source mismatch stops processing instead of rewriting the study. Full inputs remain in the verified v6 archive; reports retain unresolved positions and explicit gap counts.


## Frozen calibration fit

Before replaying segment 4,345, the declared fit produced coefficient `0.7459916645763038`. On the 616 development trades, binary log loss was `0.5148963080793826` before scaling and `0.5039266910399527` after scaling. These development values select the fixed transform; they are not forward performance evidence.
