# Strategy comparison 002 — September 30, 2026 UTC

**None of the three strategies is proven or ready for production money.** Adaptive volatility is the only positive strategy on this frozen v6 prefix, but its +$5.6672 result becomes -$15.3936 without its largest winner. It was positive on only four of ten observed UTC dates, and its 62.2% average predicted win probability exceeded its 55.5% realized win rate. The current defaults remain research settings.

## Same-data results

The comparison uses the three prospectively registered, continuously maintained forward accounts. Each starts with an independent $100 simulated bankroll, risks at most $1 per market including modeled entry fees, uses the same 500 ms delayed-IOC execution model, and sees events only in receipt order. Returns are not additive across accounts.

| Strategy | Settled | Net P&L | Return | Win rate | Fill rate | Max cost-basis drawdown | Positive UTC dates | Without largest winner |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Basic fair value | 564 | -$61.4350 | -61.44% | 40.43% | 72.94% | $97.7114 | 2/10 | -$86.5466 |
| Tail underdog | 238 | -$3.2847 | -3.28% | 19.33% | 66.76% | $40.5699 | 3/10 | -$34.5325 |
| Adaptive volatility | 616 | +$5.6672 | +5.67% | 55.52% | 76.67% | $31.0604 | 4/10 | -$15.3936 |

At the cutoff, basic fair value had two unresolved filled markets with $1.5095 at cost, tail had one with $0.6910, and adaptive had two with $1.5829. These positions are excluded from realized P&L and preserved as unresolved rather than assigned favorable outcomes.

## Interpretation

Adaptive volatility ranks first on full-prefix realized P&L, drawdown and calibration, but the margin is weak. Its profit factor is 1.025, its average profit is $0.0092 per settled trade, and removing its three largest winners changes +$5.6672 to -$42.5253. Ten observed UTC dates are below the preregistered minimum of 20 dates for the daily bootstrap interval, so no uncertainty interval is reported.

All three models were overconfident on selected trades. Average predicted probability versus observed win rate was 52.6% versus 40.4% for basic fair value, 32.3% versus 19.3% for tail, and 62.2% versus 55.5% for adaptive. Adaptive's Brier score of 0.1605 was lower than basic's 0.1707 and tail's 0.1749, but this does not remove its concentration and short-duration problems.

The adaptive Kalshi demo experiment is separate evidence. It uses demo liquidity, exchange-reported fills and a $3 cap; this forward replay uses recorded market books, simulated delayed IOC fills and a $1 cap. Their returns must not be combined or treated as independent confirmation.

## Frozen evidence

- Dataset: `e2d5cb33e7c44660809b531f03d4b4e3`
- Receipt cutoff: `2026-09-30T01:30:55.033974Z`
- Events: 425,326,032
- Archived prefix: segments 0–4,344
- Terminal segment digest: `cf620d41eb95df0912d1a26ec1708d9545a821dbb3a3442647f09bab8055f786`
- Data quality: 22 explicit gap markers, zero malformed events, zero clock adjustments
- Protected Railway evidence: `/data/comparisons/v6-002`
- Protected report SHA-256: `ea90bcccf03ce323b3984a66e97146bc3713ee59d0951706963fbb4ff30e1261`
- Protected checkpoint SHA-256: `055195a302b02cee21fb9ce99b9fe0a2dbbdd22ebce580221f4c8ef056d1b57b`

The protected directory contains the full report, HTML rendering, replay checkpoint, archive-prefix catalog and a checksum manifest. The compact committed summary is [validation/comparison-002-summary.json](validation/comparison-002-summary.json).
