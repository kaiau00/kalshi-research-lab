# Market Anchor Improvement Study 008 protocol

Registered on 2026-10-13 before calculating Study 008 results. This is a read-only development study. It cannot
submit an order, change Production, or promote a candidate. New production entries were separately paused at the
user's request before this study began.

## Fixed source

- Source: Candidate Study 003 account `adaptive_baseline`
- Dataset: `e2d5cb33e7c44660809b531f03d4b4e3`
- Source registration SHA-256: `40879e6c4a912838074963672443c25f94284603d5eedcf3f6135b8eb5e125d3`
- Frozen next segment: 7,637
- Frozen last digest: `7700cb0359bef4d775dae80b8fb2c0fb26a29a97332e7b5d2e21bd34bded504b`
- Frozen checkpoint file SHA-256: `8b3e3345cbf2eba6714ec04cdfac4927594c2a80ba67d0cb6d42dcb4b0bec1e2`

The source contains the raw adaptive model probability, Kalshi two-sided midpoint, binary spread, model timing and
uncertainty, actual 500 ms delayed fill, displayed-depth-capped quantity, fees and official result. Study 008 may
accept or reject the baseline-selected side. It may not infer an unrecorded opposite-side arrival fill.

All results from this source are development evidence. They cannot be described as untouched validation.

## Exact control

The control reproduces `market_anchor_conservative_001`: selected-side decision ask from $0.30 inclusive to $0.85
exclusive, raw-model-versus-Kalshi YES gap at most 0.06, binary spread at most $0.01, nonnegative raw selected-side
edge after a two-cent adverse-price buffer and one-contract fee, one-hour post-fill cooldown, UTC-day halts at -$2
or three consecutive settled losses, and a $5 realized-drawdown halt. It uses the recorded delayed fill and holds
to official settlement.

## Probability pool

At the start of each evaluation UTC day, fit only trades officially settled before that day's start. Require at
least five prior UTC dates and 250 settlements. The Kalshi midpoint log-odds is a fixed offset. The adjustment is a
logistic regression with L2 penalty 25 and no free intercept. Clip the raw-model-minus-market logit difference to
the closed interval [-6, 6]. Every predictor is that clipped difference multiplied by one of:

1. one;
2. absolute raw model z-score;
3. log relative model sigma in basis points;
4. seconds left divided by 300;
5. observed settlement-window fraction;
6. binary spread in cents; or
7. absolute Kalshi midpoint log-odds.

For terms two through seven, standardize the listed modifier using that training prefix only and then multiply it
by the clipped difference; the first term is the unscaled clipped difference. Use population standard deviation
and substitute one only when variance is effectively zero. This modifier-only standardization and no-intercept,
delta-interaction form force the pooled probability to equal the market midpoint when the raw model and market
agree. Coefficients are fit by penalized Newton iterations. The inverse penalized Hessian supplies an approximate
prediction variance.

For the baseline-selected side, calculate a one-sided 90% lower probability bound by subtracting 1.281551565545
standard errors from selected-side log-odds. No bootstrap observation, same-day result or future coefficient may
affect an earlier decision.

## Frozen candidates

All candidates preserve the control's agreement, spread, cooldown, realized-loss and hold rules.

- `pooled_lcb_001`: preserve the control's $0.30–$0.85 price band and require the lower-bound selected-side edge to
  remain at least 0.02 after adding two cents to the decision ask and the one-contract fee.
- `pooled_lcb_price80_001`: apply the same rule with an exclusive $0.80 maximum decision ask.
- `pooled_lcb_price80_vol90_001` (primary): also reject relative model sigma above the training prefix's 90th
  percentile. Use the nearest-rank order statistic with rank `ceil(0.90 * n)`. The percentile is recomputed from
  prior data at each walk-forward day and frozen from the complete development source before any later prospective
  run.

The two non-primary candidates are ablations. They may explain where the primary result came from, but none may be
promoted from this development comparison.

## Evaluation

Use expanding, day-ahead walk-forward evaluation. A prior date is a distinct decision UTC date represented among
rows settled before the evaluation day's start. Include every source decision date that meets the five-date and
250-settlement training requirements, including a partial final source date; report that partial status. Start the
control and every candidate with clean cooldown and realized-risk state on the first eligible evaluation date.
Apply the exact recorded delayed fill price, actual filled
quantity, exact fee and official outcome. Report settlements, wins, fees, net P&L, P&L without the three largest
winners, one- and two-cent adverse-fill stress, positive-day share, five chronological blocks, maximum drawdown,
selected-side Brier score and log loss, coefficient path, zero-training decisions, volatility rejections, cooldown
and risk-halt rejections, and unresolved exposure.

The primary development screen requires at least 30 settled selections and improvement over the exact control in
net P&L, P&L without the three largest winners, both stress tests, maximum drawdown and log loss. It must also have
positive net P&L, positive P&L without its three largest winners, positive one- and two-cent stress, more than half
of evaluation days positive and at least four positive chronological blocks.

Passing the development screen authorizes only a review. A chosen specification must receive a new immutable
registration and collect at least 20 untouched UTC dates and 100 officially settled simulated fills before any
demo or live decision.
