# Market-Shrunk Expanded Kelly-Cap Study 027 Result

Study 027 completed on 2026-10-22. Registration SHA-256:
`fe5a1cf5e1577a5e7ee18c86d51089579ef4ea6e7027d1a37f6c99b128f9f57c`. Machine-report SHA-256:
`c3e90d27ef77ba8dd77dba5abb38c512db4699a76c101ed7ca72514821926f6e`. The fixed-$1 replay reproduced Study
023's exact 838-trade ledger. Dataset 017's newest 20% holdout remained sealed.

## Results

Every path began with $100 and traded the same 838 decisions. Entry fees were included inside each cap.

| Sizing | Ending cash | Net P&L | 2-cent stress | Max drawdown | Stressed blocks | Cap binding |
|---|---:|---:|---:|---:|---:|---:|
| Quarter Kelly, $3 cap | $162.58 | +$62.58 | +$9.57 | $26.76 | 3/5 | 415/838 |
| Quarter Kelly, $4 cap | $172.47 | +$72.47 | +$7.99 | $30.51 | 2/5 | 241/838 |
| Quarter Kelly, $5 cap | $173.05 | +$73.05 | +$3.85 | $31.96 | 2/5 | 140/838 |
| Quarter Kelly, $6 cap | $175.81 | +$75.81 | +$4.20 | $33.63 | 2/5 | 58/838 |
| Half Kelly, $3 cap | $206.63 | +$106.63 | +$41.78 | $27.02 | 3/5 | 829/838 |
| Half Kelly, $4 cap | $246.62 | +$146.62 | +$56.05 | $33.30 | 3/5 | 785/838 |
| Half Kelly, $5 cap | $274.91 | +$174.91 | +$63.83 | $38.68 | 4/5 | 717/838 |
| Half Kelly, $6 cap | $294.40 | +$194.40 | +$63.20 | $52.91 | 3/5 | 662/838 |

The fixed-$1 reference made $29.6609, retained $12.1890 under two-cent stress and drew down $5.1635. Its
stress-to-drawdown ratio was 2.36, still better than every Kelly path.

## Interpretation

Increasing the quarter-Kelly cap is unattractive. Moving from $3 to $6 added only $13.2254 of base P&L, reduced
two-cent-stressed P&L by $5.3716, increased drawdown by $6.8648 and reduced stressed block consistency from three
positive blocks to two. Quarter Kelly at $3 dominates its larger-cap versions on robustness.

Half Kelly benefited from more room through $5. The $4 cap had the best two-cent-stress-to-drawdown ratio among
the eight requested paths at 1.68. The $5 cap produced the greatest two-cent-stressed P&L and was the only path
positive after stress in four of five blocks. The $6 cap added $19.4880 of base P&L over $5, but stressed P&L fell
by $0.6289 and drawdown jumped by $14.2392 to $52.9143. The $6 cap is therefore dominated by $5 on stressed
performance and carries substantially more downside.

If a future live-cap increase is justified by enough new fills, half Kelly capped at $4 is the balanced candidate;
half Kelly capped at $5 is the aggressive candidate. The historical drawdowns were $33.30 and $38.68 from a $100
starting bankroll, so neither is a small risk increase. The current live cap remains $3. Study 027 does not
authorize a production change because the underlying signal failed Study 023's original robustness gates and
this comparison reused already-viewed data.
