# Market-Shrunk Price-Band Holdout Study 026

Registration SHA-256: `258db6cd1e228ce4f98e93bfaa9da9cbc1ac19ca5f71645a746ce6721de4e100`.

Study 026 freezes the one simple candidate produced by Study 025 before Dataset 017's newest 20% is opened. The
candidate starts with Study 023's exact signal. If that signal's first selected-side ask is at least $0.65 and
below $0.70, the market is discarded. The simulator does not search later minutes for a replacement entry.

The evaluation uses fixed $1 all-in sizing, integer contracts, the existing fee calculation, hold to official
settlement, and one- and two-cent adverse-price stress. Before accessing the holdout, the runner must reproduce
both Study 023's original 838-trade ledger and the candidate's frozen 713-trade unsealed ledger by SHA-256.

## One-time gates

The holdout must contain at least 100 settled candidate trades across at least 20 UTC dates and average at least
three trades per observed date. It must win at least 65%, make money before stress, remain positive without its
three largest winners, remain positive under both one- and two-cent adverse prices, make money on more than half
of observed dates, and be positive in at least four of five blocks both before and after two-cent stress. Maximum
drawdown must not exceed $5 and the one-sided 90% lower bound for mean daily P&L must be positive.

The runner requires an explicit `--unlock-holdout` flag and refuses to overwrite an existing result. No grid,
fallback candidate or parameter adjustment is allowed after disclosure. A failure rejects the candidate. A pass
only opens a new executable-book forward shadow study; it does not authorize sizing research or a live change.

At registration time, the holdout remains sealed. Study 026 has no demo or production order path.
