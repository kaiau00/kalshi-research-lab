# Market Anchor Improvement Study 008 result

Study 008 failed its frozen development screen. This is a useful negative result: probability pooling removed the
raw model's apparent edge instead of identifying a robust subset worth forwarding to prospective validation.

## Frozen evaluation

- Frozen source: Candidate Study 003 checkpoint through segment 7,636
- Evaluation: 643 decisions across nine UTC dates, 2026-10-05 through the partial 2026-10-13 date
- Fit: expanding day-ahead prefixes; no same-day or future result entered an earlier fit
- Exact conservative control: 17 settlements, 14 wins, +$0.1627 net P&L
- Control robustness: -$0.5578 without the three largest winners, -$0.0002 at one-cent stress, -$0.1626 at
  two-cent stress, and two positive chronological blocks out of five

Across all 643 eligible decisions, Kalshi's midpoint had 0.15860 Brier score and 0.48039 binary log loss. The raw
model was materially worse at 0.16760 and 0.53626. Pooling improved the raw model to 0.15953 and 0.48377, but it
still did not beat Kalshi.

## Candidate outcome

All three frozen candidates selected zero trades. For the broad $0.30–$0.85 version, 17 decisions passed the
price, spread, and raw-model agreement filters, but the best one-sided 90% lower-bound edge after the two-cent
price buffer and fee was -$0.04566 per contract. For both $0.30–$0.80 versions, four decisions passed the common
filters and the best lower-bound edge was -$0.05122. The required lower-bound edge was +$0.02.

The primary `pooled_lcb_price80_vol90_001` candidate therefore failed the minimum sample, profitability,
concentration, stress, day-consistency, block-consistency, and calibration gates. It is rejected and is not
authorized for demo or production trading. Production remains paused.

The machine-readable report is
[`validation/market-anchor-improvement-study-008-development.json`](validation/market-anchor-improvement-study-008-development.json).
