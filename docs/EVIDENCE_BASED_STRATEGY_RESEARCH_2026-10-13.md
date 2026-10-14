# Evidence-based strategy research — 2026-10-13

This memo converts published mechanisms and this repository's results into falsifiable BTC 15-minute strategy
specifications. None is claimed profitable. A paper showing that a variable predicts prices in another market is
support for testing a mechanism, not evidence that it survives Kalshi fees, latency, depth or settlement rules.

## Facts the strategy must respect

KXBTC15M resolves from the rounded simple average of 60 BRTI observations in the minute before expiration, not a
Coinbase candle or the last BTC trade. Kalshi's own market page states this rule. CF Benchmarks describes BRTI as
an order-book aggregate across qualifying constituent exchanges and publishes the current real-time-index
methodology. Therefore, any genuine structural advantage must forecast that exact average or forecast the Kalshi
quote at which it can be bought.

The completed evidence in this repository is more important than a generic market story:

| Observation | Actual evidence | Implication |
|---|---|---|
| Raw adaptive probability failed live | 37 resolved production fills lost $37.0860; identical-entry hold lost $25.0750 although the model expected 22.54 wins and +$24.7023 | The Gaussian model was materially overconfident. Higher modeled edge was not safer |
| Early exits did not repair it | Actual monitored exits reduced aggregate P&L by $12.0110 versus holding the same entries | Exit logic cannot substitute for entry edge |
| Kalshi midpoint beat the raw and pooled models | Study 008 scored 643 eligible decisions; the market midpoint had better Brier score and log loss, and every lower-bound pool selected zero trades | New models must show incremental information over the market, not merely disagree with it |
| Broad parameter search was fragile | Study 004 tested 40 frozen configurations; none passed all gates and none stayed positive without the three largest winners | More threshold grids are unlikely to solve the problem |
| The cheap-tail idea lacks support | Tail demo lost $0.7094 on 10 settlements; the two shadow windows generated only 5 and 6 signals | Do not prioritize the original tail strategy |
| Rollover structure is real | 1,893 usable adjacent archived pairs had exact prior-final-to-next-target handoff with zero mismatches | Rollover Bridge has a verified contract-specific state variable |
| Moderate disagreement is only a lead | The selected 45-trade development slice made +$5.8736 and survived the recorded stress screens | Study 009 deserves prospective observation, but selection on viewed data means the result is not proof |

## Ranked research program

### 1. Finish Rollover Bridge Study 007

This remains the highest-priority existing-data project because its input is created by the contract design and is
already verified in our archive. At the new contract's open,

```text
K_n = A_(n-1)                       exact previous official settlement average
g_n = log(S_open / K_n)             endpoint-versus-average gap
u_n = sum w_j * r_(n-j)             filtered prior-minute velocity
```

The development model treats Kalshi's midpoint as the prior probability, then fits only shrinkage adjustments for
`g_n`, velocity, jump share and observation offset. The decisive questions are prequential log loss against the
midpoint and executable P&L after 500 ms, fees, depth and two cents of stress. The verified handoff supports the
feature; it does not show that traders fail to price it.

**Falsification:** reject the directional model if it does not beat the midpoint on later dates or if positive P&L
depends on its three largest wins. A useful null result would still show that the opening market absorbs the
handoff efficiently.

### 2. Market-calibrated favorite model (`market_beta_calibrated_favorite_010`)

Study 008 says the market should be the base model. Published prediction-market research finds calibration can
vary with price and time to expiration, and a new Polymarket study reports aggregate losses for sub-10-cent buys
and small gains for 90-cent-and-above buys across 588 million trades. That is relevant evidence against our tail
underdog instinct, but it is not Kalshi KXBTC15M evidence.

Fit a beta calibration on prior UTC days only:

```text
logit(p_cal) = c + a * log(p_market) - b * log(1 - p_market)
```

Use a small fixed set of time-to-close strata because expiration time can affect calibration. Shrink `(a,b,c)`
toward the identity `(1,1,0)`. For a selected side with arrival ask `q`, trade only if a one-sided lower confidence
bound satisfies

```text
LCB(p_cal) - [q + fee(1,q) + adverse_price_cost] >= required_margin.
```

This is not permission to search arbitrary favorite bands. Development should compare the identity market model,
one global beta calibration and one preregistered time-stratified version. The candidate must be fit at day `d`
using results finalized before day `d`.

**Falsification:** abandon it if calibration gains do not translate into positive two-cent-stressed executable
P&L, or if the lower bound produces too few trades for a meaningful forward test.

### 3. Jump-robust HAR settlement model (`jump_robust_har_settlement_011`)

The current model blends two mean-squared-return windows and assumes a Gaussian diffusion. Realized-volatility
research provides parsimonious alternatives. Bipower variation separates continuous variance from infrequent
jumps, and HAR-RV represents persistent volatility with a small linear model. Bitcoin-specific research finds
that jumps and signed variation can improve some out-of-sample volatility forecasts, while also finding that the
benefit can disappear at short horizons. That mixed result is a reason to test a small model, not a large Hawkes
system.

For one-second returns in window `h`:

```text
RV_h  = sum r_i^2
BPV_h = (pi/2) * sum |r_i| |r_(i-1)|
J_h   = max(RV_h - BPV_h, 0)
RS+_h = sum r_i^2 * 1[r_i > 0]
RS-_h = sum r_i^2 * 1[r_i < 0]
```

Fit on prior dates only:

```text
log(RV_future) = beta_0
               + beta_1 log(RV_60)
               + beta_2 log(RV_300)
               + beta_3 log(RV_1800)
               + beta_4 J_300 / RV_300
               + beta_5 (RS+_300 - RS-_300) / RV_300 + epsilon.
```

Use strong ridge shrinkage and Student-t residuals. Simulate the remaining one-second BRTI path, insert already
observed settlement seconds exactly, take the arithmetic average, round to cents, and estimate the crossing
probability. Compare three prespecified models: current adaptive Gaussian, HAR without jump/sign terms, and full
jump-robust HAR. No hidden-regime or Hawkes parameters are added unless this simpler test wins prospectively.

**Falsification:** reject if it fails to improve midpoint-relative log loss, calibration and two-cent-stressed
P&L on later UTC dates. A better volatility forecast alone is insufficient.

### 4. Quote-innovation error correction (`quote_innovation_error_correction_012`)

Study 009's development slice suggests that moderate raw-versus-market disagreement may behave differently from
large disagreement. Model that relationship directly instead of imposing another static band. Let

```text
x_t = logit(p_structural,t)
m_t = logit(p_market,t)
e_t = x_t - m_t
e_(t+1) = alpha + rho * e_t + gamma' z_t + noise.
```

`z_t` contains only prespecified state variables available at receipt time: seconds left, observed fraction of the
settlement window, spread and relative model sigma. Estimate `rho` on prior days and calculate the expected
disagreement at the 500 ms arrival time. An entry requires that the conservative probability implied by the
surviving innovation still beats arrival cost under stress.

This is lower priority than Studies 007, 009 and candidate 010 because its only direct repo support is a selected
development slice. It is valuable mainly as a clean test of whether disagreement decays before execution.

**Falsification:** reject if `rho` is unstable across chronological blocks, if residuals do not predict future
market probability conditional on the current midpoint, or if the effect vanishes at actual arrival.

### 5. Order-flow execution overlay (`order_flow_execution_overlay_013`)

Cont, Kukanov and Stoikov found that short-horizon price changes were more robustly related to order-flow imbalance
than to trade volume, with impact inversely related to depth. Stoikov's microprice uses spread and queue imbalance
to estimate future midprice and beat plain midpoint in the paper's data. Those studies support an execution test,
not Kalshi outcome prediction.

For each Kalshi book event, compute level-weighted flow imbalance and a simple best-level microprice:

```text
OFI_t = added_bid - removed_bid - added_ask + removed_ask
micro_t = (ask * bid_depth + bid * ask_depth) / (bid_depth + ask_depth).
```

Fit a regularized model for the selected-side executable ask 500 ms ahead and the probability that displayed depth
survives. Compare trade-now, wait-one-update and reject policies on a chronological holdout. The settlement model
and signal selection remain fixed.

**Falsification:** reject if it does not lower actual arrival cost or reduce adverse selection after fees. Never
report next-quote accuracy as settlement alpha.

### 6. BRTI Shadow Index (`brti_shadow_index_014`)

This has the clearest path to genuinely new information because BRTI itself aggregates constituent order books.
The official methodology is public, but exact replication requires synchronized constituent depth, source and
receipt timestamps, sequence-gap handling, clock-offset measurement, current constituents and attention to data
licensing. The current archive cannot backtest it.

The target is the conditional distribution of future official BRTI observations, not a generic spot price:

```text
BRTI_t = alpha_t + beta_t * replica_t + epsilon_t
[alpha_t, beta_t] = [alpha_(t-1), beta_(t-1)] + state_noise.
```

Only after an out-of-sample lead-lag study should the replica feed the exact remaining-settlement-average
simulation. A Coinbase-only feed is not an acceptable substitute.

**Falsification:** stop if the partial replica does not lead the official Kalshi BRTI feed after measured network
latency, or if residual uncertainty is larger than the executable edge.

### 7. Complement parity monitor (`complement_parity_monitor_015`)

For a binary market, buying one YES and one NO guarantees $1 at settlement. A true executable arbitrage requires

```text
ask_yes + ask_no + fee_yes + fee_no < 1
```

at the same moment with independently executable depth. This is a useful data-integrity monitor. Kalshi's YES and
NO representations may be complements of the same order book rather than two independent pools, so an apparent
violation can be a conversion or timestamp error. Implement it only as a simultaneous-depth audit first.

**Falsification:** if every apparent violation disappears after exact book conversion, fees and common receipt
time, retain it as an invariant check rather than a strategy.

## What the research does not support

- **More tail buying:** both repo evidence and external favorite-longshot evidence point the other way. The external
  result is not enough to trade favorites on Kalshi, but it removes the rationale for assuming cheap contracts are
  inherently underpriced.
- **A larger AI model:** we have many decisions but few independent market regimes and days. A flexible model can
  memorize the same paths reused across decisions. It must first beat the midpoint and the low-dimensional models
  above in a locked chronological test.
- **Kelly as a strategy:** Kelly optimizes growth only when `p` is accurate. The live audit shows ours was not.
- **Early-exit optimization:** the completed counterfactual audit was materially negative.
- **Standalone Hawkes outcome prediction:** event intensity can help forecast the next quote. Published
  microstructure evidence does not establish final-settlement alpha.

## Evidence standard for any new candidate

1. Create one immutable specification before its first prospective timestamp.
2. Use receipt-ordered inputs and the exact first book at or after 500 ms; cap fills to displayed integer depth.
3. Compare probability quality with the contemporaneous Kalshi midpoint using prequential log loss, Brier score
   and reliability, not P&L alone.
4. Deduplicate inference by UTC day or market; repeated one-second decisions are not independent samples.
5. Report every attempted model and correction for selection. Use time-uniform confidence sequences for repeated
   monitoring rather than treating each daily look as a fresh fixed-sample test.
6. Require positive net P&L without the three largest winners, at one- and two-cent adverse fills, on a majority of
   days and in four of five chronological blocks. Preserve unresolved exposure.
7. A passing read-only study advances to a separately frozen demo-execution audit. It does not authorize live
   trading.

## Primary sources

- [Kalshi KXBTC15M market and final-minute average rule](https://kalshi.com/markets/kx/test/kxbtc15m-26sep082030)
- [Kalshi fees](https://help.kalshi.com/en/articles/13823805-fees)
- [CME CF Bitcoin Real Time Index](https://www.cfbenchmarks.com/data/indices/BRTI)
- [CME CF Real-Time Index Methodology, version 16.5](https://docs.cfbenchmarks.com/CME%20CF%20Real%20Time%20Indices%20Methodology.pdf)
- [Corsi, A Simple Approximate Long-Memory Model of Realized Volatility](https://academic.oup.com/jfec/article/7/2/174/856522)
- [Barndorff-Nielsen and Shephard, Power and Bipower Variation with Stochastic Volatility and Jumps](https://doi.org/10.1093/jjfinec/nbh001)
- [Yu et al., Risk of Bitcoin Market: Volatility, Jumps, and Forecasts](https://arxiv.org/abs/1912.05228)
- [Cont, Kukanov and Stoikov, The Price Impact of Order Book Events](https://arxiv.org/abs/1011.6402)
- [Stoikov, The Micro-Price](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2970694)
- [Kull, Silva Filho and Flach, Beta Calibration](https://proceedings.mlr.press/v54/kull17a.html)
- [Page and Clemen, Do Prediction Markets Produce Well-Calibrated Probability Forecasts?](https://doi.org/10.1111/j.1468-0297.2012.02561.x)
- [Cardozo and Rivero-Wildemauwe, Favorite-Longshot Bias in Prediction Markets](https://arxiv.org/abs/2609.12878)
- [Howard et al., Time-uniform, nonparametric, nonasymptotic confidence sequences](https://arxiv.org/abs/1810.08240)

## Recommendation

Do not start another broad strategy search. Finish the already registered Rollover Bridge development analysis and
continue the untouched Study 009 monitor. In parallel, implement candidates 010 and 011 as read-only expanding-day
comparisons against the Kalshi midpoint. Build candidate 013 only after those forecast tests, because better fills
cannot rescue a negative settlement edge. Candidate 014 requires a separate data-acquisition decision and cost
estimate before code.
