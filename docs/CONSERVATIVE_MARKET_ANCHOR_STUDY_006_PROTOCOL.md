# Conservative Market Anchor Study 006

Declared on October 10, 2026 before the prospective cutoff at 2026-10-10 18:00:00 UTC. This study filters only
future `adaptive_baseline` fills from the unchanged Candidate Study 003 checkpoint. It has no order-submission
path and does not alter Candidate Study 003 or Market Anchor Study 005.

The frozen candidate is `market_anchor_conservative_001`. It preserves the raw adaptive-volatility signal,
4% minimum modeled net edge, 5–300 second entry window, $1 fixed risk, 500 ms delayed IOC simulation, and official
settlement. It additionally requires:

- selected-side ask at least $0.30 and below $0.85;
- absolute raw-model versus Kalshi two-sided midpoint gap no greater than 0.06;
- binary spread no greater than $0.01;
- nonnegative modeled edge after adding $0.02 to the selected ask and applying the modeled entry fee;
- one hour between filled candidate entries;
- a UTC-day halt at -$2 realized P&L or three consecutive settled losses; and
- an indefinite halt at $5 maximum realized drawdown.

Review requires at least 20 prospective UTC dates and 50 officially settled candidate fills. The candidate must
have positive net P&L, remain positive without its three largest winners, remain positive under one- and two-cent
adverse fills, be positive on more than half of observed days and in four of five chronological blocks, and keep
maximum drawdown at or below $5. Reaching the counts does not prove an edge. No parameter may be changed from
prospective results.

The exploratory evidence used to choose this single configuration is limited. Applied to the Study 004
development window it selected 14 trades, earned $0.5380, earned $0.2703 under two-cent stress, and had $0.8304
drawdown. Applied once to the later pre-prospective Study 003 window it selected 14 trades, earned $0.6152,
earned $0.3472 under two-cent stress, and had $0.8495 drawdown. Both windows became slightly negative after
removing their three largest winners. On the already observed 37-trade live Market Anchor ledger it selected only
three trades and lost $0.3566. These are development diagnostics, not forward evidence.
