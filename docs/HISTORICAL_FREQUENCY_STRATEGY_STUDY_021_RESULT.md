# Historical Frequency Strategy Study 021 Result

Study 021 completed its preregistered 11,520-cell development grid on 2026-10-18. No configuration passed every
development gate, so the later validation partition, the risk comparison and Dataset 017's final holdout remained
closed. The registration SHA-256 is `d85d9c8c6c2e656c0ae8468243e4c1062cf9bb2383fd3f4432c695754f8b710b` and
the full machine-report SHA-256 is `9d54439acc1ddf16280b98796b46e5f16fc6d2aec29be177ba9646153bb2ad40`.

## Frequency target

Of the 11,520 configurations:

- 1,297 averaged 8–12 trades across all 110 development UTC dates;
- 483 also won at least 65% and had a mean entry price from 45 to 72 cents;
- 165 of those made positive base P&L;
- only one of those remained positive after adding two cents to every entry.

That sole two-cent-positive high-frequency cell used the neutral drift model, 60% fast variance weight, 10% Kalshi
log-odds pooling, a 2.5% edge floor, 45–85 cent entry band, 10-point model/market gap, 5–300-second window and
two-cent spread limit. At fixed $1 it produced:

| Metric | Development result |
|---|---:|
| Trades | 889 |
| Trades per observed day | 8.08 |
| Win rate | 72.67% |
| Mean entry price | 68.85 cents |
| Net P&L | +$19.1355 |
| P&L without three largest winners | +$15.9396 |
| One-cent adverse-price P&L | +$9.7333 |
| Two-cent adverse-price P&L | +$0.3421 |
| Positive-day share | 52.73% |
| Maximum drawdown | $17.7168 |

Its five base blocks were `+$6.7999`, `+$14.2839`, `-$8.2404`, `-$3.3320`, and `+$9.6241`. Under two-cent
stress they were `+$2.1783`, `+$9.8214`, `-$10.9542`, `-$6.2911`, and `+$5.5877`. The one-sided 90% lower bound
for mean daily P&L was negative. It therefore failed drawdown, four-of-five base consistency, four-of-five stressed
consistency, and daily-mean uncertainty gates. Validation was not opened.

The cell closest to ten trades per day averaged 9.79, won 71.8%, entered at 68.4 cents on average and made
+$18.7343 before stress. It lost $4.2082 under two-cent stress and drew down $18.6857, so frequency did not create
a durable edge.

## Strategy-family finding

The neutral zero-drift family generated the viable high-frequency cells. Mild momentum produced the strongest
robustness profile, but its best cell averaged only 2.16 trades per day. Mean reversion and stronger momentum were
sparse, tended toward expensive entries, or failed the profit and uncertainty gates. The best mild-momentum cell
made $17.4324 across 238 trades, won 71.01%, entered at 64.33 cents on average, retained $12.0291 under two-cent
stress and drew down $8.8637; it failed only the requested frequency gate.

## Decision

Study 021 has no candidate. No sizing comparison is valid because changing risk cannot fix chronological losses or
negative stressed expectancy. The final holdout remains sealed, and no demo or production order is authorized.

The result suggests that the requested ten-trade frequency and robust two-cent economics conflict under this
structural-model family. The next test should change the source of edge rather than search smaller threshold steps:
use stronger market-probability shrinkage with a conservative disagreement cap, or test a quote-momentum execution
family separately. Any such follow-up must be preregistered and retain the same frequency, stress and chronology
requirements.
