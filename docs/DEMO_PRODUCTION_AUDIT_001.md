# Demo versus production audit 001

**Decision: the adaptive demo profit does not transfer cleanly to the production-data replay.**
The demo account remains useful for testing order handling, but its headline return should not be treated as
evidence of an executable production edge.

## Frozen snapshot

- 114 settled adaptive-volatility demo fills
- $32.715900 exchange-reported demo net P&L
- Production replay through archived segment 6,051
- Original production adaptive account before segment 4,345, then the unchanged `adaptive_baseline`
  Candidate Study 003 account
- Same BTC `KXBTC15M` ticker, side, model definition and official threshold comparison

The audit reads the already-verified production replay checkpoints. It does not download or replay the
189 million raw events covering the demo period again. For each demo fill it finds the nearest independent
production adaptive order on the same ticker and measures side and decision-time agreement.

## Result

| Check | Result |
|---|---:|
| Demo fills | 114 |
| Same ticker had a production adaptive order | 106 |
| Same-side production fill at any time in the market | 64 |
| Same-side production fill within 60 seconds | 46 |
| Same-side production fill within 10 seconds | 25 |
| Same-side production fill within 2 seconds | **14** |
| Demo P&L from the 14 close matches | **+$4.4283** |
| Production replay P&L from those 14 matches | **+$3.4251** |
| Demo P&L without a close same-side match | **+$28.2876** |
| Top five demo wins with a close same-side match | **0 / 5** |

All 106 comparable nearest production orders had the same inferred effective threshold as the demo decision;
the maximum threshold difference was zero. The mismatch is therefore not explained by different contract
terms. Demo and production prices, forecast timing or quote availability caused different decisions.

Ten demo fills had a production adaptive decision within two seconds on the **opposite side**. Those ten demo
trades contributed +$19.5350, including the largest +$10.2544 demo winner. Only 20 nearest production orders
within two seconds chose the same side, and six of those did not fill in the production replay.

The five largest demo wins contributed $30.8627 of the $32.7159 total. None had a same-side production fill
within two seconds. The largest demo winner bought NO around $0.20; 0.70 seconds earlier the production replay
bought YES around $0.70 on the same threshold and lost $0.7147.

## Interpretation

The result strongly indicates that most of the unusually high demo return came from opportunities specific to
the demo order book. The production-data adaptive replay often did not select the same side at the same time,
and the biggest demo wins do not have close production counterparts.

This retrospective checkpoint match cannot prove the exact production quote when no production order was
created. An absent order can mean insufficient edge, invalid inputs, a different earlier entry or unavailable
execution. The full comparison is preserved in
[`validation/demo-production-audit-001.json`](validation/demo-production-audit-001.json).

## Exact capture going forward

Deployment `0cc46d37-aeef-4510-bf9f-f34fbb6b8d5c` adds direct production snapshots to every new demo order.
Without delaying submission, it records the production threshold, YES/NO asks, displayed depth, quote age,
adaptive forecast, selected-side edge, fee support and qualification state at the demo signal. It captures the
same fields again at the declared 500 ms arrival time. Both snapshots are committed to the demo journal and
the verified segmented demo archive.

The adaptive strategy, 5–300 second window, 4% edge threshold and $3 demo cap remain unchanged. The new code
has no production-order path.
