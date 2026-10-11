# Advanced BTC 15-minute strategy research

Research memo dated 2026-10-10. None of these candidates is authorized for live orders. The active production
strategy remains frozen while these ideas are developed and tested in read-only studies.

## Research conclusion

The next useful strategy should not be another grid search over edge, time, or price thresholds. The existing
adaptive family has already shown that a precise-looking probability can be badly wrong in production. The best
new directions use information the current model omits: the mechanical handoff between consecutive contracts,
the construction of the settlement index, non-Gaussian jumps and regimes, and event-level order-book dynamics.

The candidates are ranked as follows:

1. **Rollover Bridge** — best candidate that the current archive can test.
2. **BRTI Shadow Index** — highest potential information advantage, but it requires new constituent-exchange data.
3. **Jump-Robust Settlement Filter** — strongest replacement for the current Gaussian probability model.
4. **Hawkes Reaction-Delay Overlay** — potentially improves entry timing and execution; not standalone outcome alpha.
5. **Robust Probability Pool and Evidence Gate** — required protection around any candidate; not a strategy by itself.

Complexity is useful only when it represents a real feature of the contract. A deep neural network or reinforcement
learner trained on the current sample would have more parameters than reliable independent days and would be easy
to overfit. It is intentionally excluded from the first research round.

## 1. Rollover Bridge

### Structural idea

Consecutive KXBTC15M contracts are linked. The next contract's target is the prior contract's final 60-second BRTI
average. For example, the market ending at 2:45 p.m. ET on 2026-08-09 finalized at $65,165.09, and the next market
used exactly $65,165.09 as its target. The new market therefore begins with a strike that is a lagged path average,
while the current BRTI is the endpoint of that path.

A read-only audit of the v6 catalog on 2026-10-10 found 1,893 usable adjacent market pairs. Every pair matched
exactly: the earlier market's official `expiration_value` equaled the dollar target displayed for the next market.
There were zero mismatches. This verifies the handoff mechanism in our own data; it does not yet show that trading
the mechanism is profitable.

That creates a state variable the current strategy discards:

```text
K_n       = A_(n-1)                         prior 60-second arithmetic average
g_n       = log(S_open / K_n)               endpoint-versus-average gap
v_open    = posterior short-horizon velocity at rollover
```

The gap alone is not an edge; an efficient market can price it. The hypothesis is that the combination of the gap,
the shape of the prior minute, and the first seconds of the new Kalshi book contains information that is not fully
reflected in the executable quote.

### Model

Use an integrated Ornstein-Uhlenbeck velocity model with a hidden volatility/jump regime:

```text
dX_t = v_t dt + sigma_(z_t) dW_t
dv_t = -kappa_(z_t) (v_t - theta_(z_t)) dt + eta_(z_t) dB_t
P(z_(t+dt)=j | z_t=i) = Q_ij dt
```

`X_t` is log BRTI and `z_t` is a small Markov regime such as quiet, directional, or jump recovery. A Kalman filter
handles the linear Gaussian portion; a Rao-Blackwellized particle filter integrates regime uncertainty. Each
particle simulates the remaining BRTI path and the actual arithmetic settlement average, including cent rounding:

```text
p_yes = sum_m w_m * 1[round(A_close^(m), 2) >= K_n]
```

The executable rule uses the lower posterior bound rather than the posterior mean:

```text
robust_edge_yes = quantile_05(p_yes) - ask_yes - fee - latency_slippage
```

Trade only if the robust edge remains positive after the frozen adverse-price stress. This turns parameter and
regime uncertainty into a reason not to trade.

### Why it is promising

- It is specific to the way these consecutive contracts are constructed.
- It can act near rollover, a part of the market the current 5–300 second entry window ignores.
- It uses the full path of the prior settlement minute instead of only a rolling variance.
- The current v6 archive records BRTI and pre-subscribes upcoming Kalshi books, so it can be tested after an explicit
  opening-coverage audit.

### Primary failure mode

The market may already incorporate the rollover gap instantly. The test must use executable arrival quotes and
must compare against the Kalshi midpoint baseline. A directional forecast that does not outperform the quote is
not an edge.

## 2. BRTI Shadow Index

### Structural idea

KXBTC15M settles from BRTI, not from one exchange's last trade. BRTI consolidates order books from constituent
exchanges, caps abnormal displayed size, uncrosses the consolidated book, constructs bid and ask price-volume
curves, and exponentially weights their mid-price curve. The official index is published about once per second,
while constituent books update much faster.

Build an independent subsecond approximation of BRTI from the constituent exchanges:

```text
askPV(v) = executable ask price for cumulative size v
bidPV(v) = executable bid price for cumulative size v
midPV(v) = (askPV(v) + bidPV(v)) / 2

BRTI_hat = sum_v midPV(v) * lambda * exp(-lambda*v) / normalization
```

Use the published dynamic size-cap and spacing rules where inputs permit. A state-space model estimates the mapping
between the partial replica and official BRTI:

```text
BRTI_t = alpha_t + beta_t * replica_t + epsilon_t
[alpha_t, beta_t]' = [alpha_(t-1), beta_(t-1)]' + process_noise
```

The signal is not simply `replica - BRTI`. It is the posterior distribution of the next official BRTI observations
and their contribution to the contract's remaining settlement average. Entries still require an executable Kalshi
quote after measured latency and fees.

### Why it is promising

- It targets the exact settlement source.
- It may see constituent order-book movement before the once-per-second BRTI publication and before Kalshi reprices.
- It provides an independent forecast rather than another transformation of the same BRTI history.

### Data requirement

The current recorder cannot test this. Add synchronized level-2 books for the active BRTI constituents, currently
including Bitstamp, Coinbase, Kraken, Gemini, Bullish, Crypto.com, and LMAX Digital, subject to feed access and
licensing. Record source and receipt timestamps, sequence gaps, reconnects, and clock offset. Partial replication
must be labeled as such; it cannot be called BRTI.

### Primary failure mode

Public feeds may be slower than the official calculation input, and incomplete constituent coverage can create a
stable-looking but useless residual. This candidate earns priority only after measuring lead-lag out of sample.

## 3. Jump-Robust Settlement Filter

### Structural idea

The existing forecast assumes locally stable Gaussian diffusion. Fifteen-minute BTC paths contain volatility
regimes and jumps, and binary payouts are unusually sensitive to tail probability near the target. Separate
continuous variance from jumps before computing the settlement probability.

For one-second log returns `r_i`, estimate realized and bipower variation:

```text
RV = sum_i r_i^2
BV = (pi/2) * sum_i |r_i| * |r_(i-1)|
J  = max(RV - BV, 0)
```

Use a small hidden Markov model for the continuous variance and a self-exciting jump intensity:

```text
lambda_t = mu_z + sum_(tau_j<t) alpha_z * exp(-beta_z * (t-tau_j))
r_t = drift_z*dt + sigma_z*dW_t + Y_t*dN_t
```

A sequential particle filter propagates remaining one-second BRTI values, inserts already observed settlement
seconds exactly, and estimates the probability of the rounded final arithmetic average crossing the target. Use
Student-t or empirical jump sizes rather than a normal tail.

### Why it is promising

- It attacks the largest known modeling weakness rather than tuning the entry threshold.
- It uses data already present in the v6 archive.
- It naturally produces probability uncertainty and can abstain after regime changes.

### Primary failure mode

There may be too few independent jump episodes to estimate a Hawkes model reliably. The first version should use
very few regimes, strong shrinkage, and fixed parameter-selection rules. More apparent fit is not evidence.

## 4. Hawkes Reaction-Delay Overlay

### Structural idea

The v6 archive contains dense Kalshi order-book deltas. Model bid additions, bid removals, ask additions, and ask
removals as mutually exciting point processes:

```text
lambda_k(t) = mu_k + sum_j sum_(tau in events_j, tau<t)
                       alpha_(k,j) * exp(-beta_(k,j) * (t-tau))
```

Combine those intensities with multi-level order-flow imbalance:

```text
OFI_h = added_bid_h - removed_bid_h - added_ask_h + removed_ask_h
```

Estimate the distribution of the executable ask after the real 500 ms delay. The overlay chooses between trade now,
wait, or reject using an optimal-stopping value function:

```text
V(state,t) = max(EV_trade_now, E[V(next_state,t+dt)], 0)
```

The settlement probability must come from an independent model. This overlay is useful only if it improves actual
entry cost or avoids adverse selection after fees.

### Why it is feasible

A recent seven-minute v6 segment contained roughly 192,000 KXBTC15M order-book deltas and 456 BRTI messages. The
event density supports point-process work, provided snapshots and deltas are reconstructed across segment boundaries
without gaps.

### Primary failure mode

Order-book pressure can predict the next quote without predicting the outcome. It may merely explain why waiting
causes the edge to disappear. That can still improve execution, but it must not be reported as settlement alpha.

## 5. Robust Probability Pool and Evidence Gate

Every candidate should compete with the market rather than replace it blindly. Pool the market probability,
structural settlement model, and any microstructure model in log-odds space:

```text
logit(p_pool) = w_0 + w_m logit(p_market)
                   + w_s logit(p_structural)
                   + w_o microstructure_score
```

Estimate weights sequentially with shrinkage toward `w_m=1`, `w_s=w_o=0`. This makes the Kalshi quote the prior
baseline and requires new features to demonstrate incremental out-of-sample information. Use a posterior or online
conformal error band and submit a simulated order only when the lower edge bound clears fees, spread, depth, latency,
and adverse-price stress.

This layer also controls research selection. Freeze each candidate before its first prospective date; report every
candidate, including failures; and use daily blocks for uncertainty. Do not choose whichever model has the highest
headline P&L.

## Testing order

### Phase A — data and falsification

1. Audit the latest v6 opening coverage, book reconstruction across segments, and exact consecutive-target handoff.
2. Build one shared decision tape containing only information available at each receipt timestamp.
3. Add Rollover Bridge, Jump-Robust Settlement, and the existing market probability as frozen forecast columns.
4. Fit Hawkes execution only on training days and score the fixed model on later days.
5. Keep all studies read-only; do not alter production.

### Phase B — robustness screen

For every candidate require:

- executable 500 ms delayed IOC simulation with best-level integer depth;
- positive P&L after one-cent and two-cent adverse fills;
- positive P&L after removing the three largest winners;
- positive results in at least four of five chronological blocks;
- positive-day share above 50%;
- calibrated probabilities and better prequential log loss than the Kalshi midpoint;
- latency stress at 1 and 2 seconds;
- results by volatility, spread, price, side, time-to-close, and UTC-hour regime;
- at least 20 untouched UTC dates and a prespecified minimum number of settlements;
- no unresolved exposure, invented fills, backfilled data, or parameter changes during the forward window.

### Phase C — new-data pilot

Only after the current-data candidates are frozen should the recorder add constituent-exchange feeds for the BRTI
Shadow Index. Run it as a separate dataset and compare partial-replica lead-lag against the official BRTI feed before
using any Kalshi outcome or P&L.

## Sources

- [Kalshi KXBTC15M example and settlement rule](https://kalshi.com/markets/kx/test/kxbtc15m-26jul242215)
- [Earlier market in an observed adjacent pair](https://kalshi.com/markets/kx/test/kxbtc15m-26aug091445)
- [Adjacent contract showing prior final as the next target](https://kalshi.com/markets/kx/test/kxbtc15m-26aug091500)
- [CF Benchmarks BRTI description](https://www.cfbenchmarks.com/data/indices/BRTI)
- [CME CF Real-Time Index Methodology](https://docs.cfbenchmarks.com/CME%20CF%20Real%20Time%20Indices%20Methodology.pdf)
- [Current CME CF constituent exchanges](https://docs.cfbenchmarks.com/CME%20CF%20Constituent%20Exchanges.pdf)
- [Stoikov, The Micro-Price](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2970694)
- [Cont, Kukanov and Stoikov, The Price Impact of Order Book Events](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1712822)
- [Cestari et al., Hawkes-based cryptocurrency forecasting](https://arxiv.org/abs/2312.16190)
- [Barndorff-Nielsen and Shephard, Power and Bipower Variation](https://doi.org/10.1093/jjfinec/nbh001)
- [Kalshi-wide prediction-market calibration study](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7355520)
