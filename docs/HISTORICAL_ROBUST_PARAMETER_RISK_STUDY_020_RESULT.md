# Historical Robust Parameter and Risk Study 020 Result

Study 020 completed its preregistered 4,608-configuration development search on the already-viewed first 80% of
Dataset 017. No configuration passed every stronger-than-Study-019 gate. The newest 20%, containing 3,463
markets, remains sealed and unevaluated. No sizing comparison, demo order or production order was authorized.

The registration SHA-256 is `ff31bcf42c88bf58b1733d2106846a0bc854192b426d6f56eb91f450f719e76f`.
The local machine report SHA-256 is `fef62f8f25326570a4482d561b9f5b19b4534fcd1f9dae3881d9ccbd996d848c`.

## What improved and what did not

The search did find configurations with larger headline returns. There were 288 configurations above Study 019's
$11.9751 fixed-$1 P&L, and 76 simultaneously exceeded its base P&L, P&L without the three largest winners and
two-cent-stressed P&L. None also satisfied every time-consistency, drawdown, sample and confidence gate.

The strongest stressed-P&L near miss was `v90_w00_e035_p4580_g075_t005300_s02_b00`:

- 90% weight on 60-second variance and 10% on 600-second variance;
- raw probability with no interpolation toward Kalshi's midpoint;
- at least 3.5% modeled net edge;
- selected-side ask from $0.45 inclusive to $0.80 exclusive;
- raw-model-versus-market gap no greater than 7.5%;
- entry from 5 through 300 seconds before close;
- binary spread no greater than two cents; and
- nonnegative edge after adding two cents and the one-contract fee.

| Fixed-$1 result | Trades | Wins | Net P&L | Ex top 3 | +1 cent | +2 cents | Positive days | Drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Study 020 near miss | 727 | 511 | +$24.4806 | +$21.2847 | +$16.8465 | +$9.2233 | 84/147 | $6.1114 |
| Study 019 lead | 549 | 415 | +$11.9751 | +$10.5276 | +$6.6574 | +$1.3466 | 79/147 | $6.5425 |

The near miss also remained positive in the original development and validation partitions. Development made
$19.0319 and +$8.3097 at two-cent stress. Validation made $5.4487 and +$0.9136 at two-cent stress. Its one-sided
90% lower bound for mean daily P&L was positive on the combined research interval.

It nevertheless failed the frozen time-consistency gate. Its five two-cent-stressed blocks made $7.7118,
$6.4051, -$5.1120, $1.9170 and -$1.6986, so only three of five were positive. This is not a technicality: the
third block's loss consumed more than half of the strategy's total stressed profit. Eighteen configurations missed
only one gate, but the best-performing neighborhood repeatedly showed the same stressed-block instability.

The highest headline configuration made $27.5030 across 1,417 trades, but lost $2.0356 under two-cent stress,
had $14.1937 maximum drawdown and was positive in only three of five base blocks. This demonstrates why choosing
only the largest P&L would create a worse strategy.

## Risk result

The preregistration allowed fixed $1, $1.50, $2 and $3 plus one-sixteenth and one-eighth Kelly only after a signal
passed every fixed-$1 gate. No signal passed, so the risk comparison was correctly left unopened. Increasing size
would multiply the same negative stressed blocks; it cannot repair the missing time consistency. Study 019's
fixed-$1 recommendation therefore remains the only supported research sizing.

## Decision

Study 020 has no winner. The high-P&L near miss is preserved as a development hypothesis, not promoted. Opening
the sealed historical holdout after relaxing the failed block gate would be post-result rule changing, so the
holdout remains locked. A defensible next test would freeze the near miss unchanged and collect a new forward,
read-only executable-book sample; that test cannot reuse the already-viewed Study 020 interval as validation.

The complete local report is `reports/historical-robust-parameter-risk-study-020.json`. The tracked
[sanitized summary](validation/historical-robust-parameter-risk-study-020-summary.json) preserves the reproduced
Study 019 lead, the strongest stressed near miss, the highest headline configuration, gate counts and report
hashes.
