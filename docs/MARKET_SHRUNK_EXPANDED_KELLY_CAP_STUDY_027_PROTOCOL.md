# Market-Shrunk Expanded Kelly-Cap Study 027

Study 027 is a risk-only backtest on Study 023's exact 838 historical decisions. It compares quarter Kelly and
half Kelly with maximum all-in entry costs of $3, $4, $5 and $6. Every path starts with $100, buys integer
contracts, includes Kalshi entry fees inside the cap and holds to official settlement.

The base quantity is preserved when entries are repriced one and two cents adversely. The report compares net
P&L, P&L without the three largest winners, stressed P&L, drawdown, positive days and blocks, contracts, fees,
cap-binding frequency and stress-to-drawdown ratio. Study 024's fixed-$1 ledger must replay exactly before any
expanded-cap result is accepted.

This study uses only Dataset 017's already-viewed oldest 80%. The newest 20% holdout remains sealed. It cannot
establish signal edge, authorize a live cap increase or change the current production bot.
