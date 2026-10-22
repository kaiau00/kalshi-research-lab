# Market-Shrunk Half-Kelly $5 Production 001

On October 22, 2026, the user explicitly authorized changing the active BTC 15-minute Predictions bot from the
Study 023 half-Kelly rule capped at $3 to the identical signal and half-Kelly rule capped at $5. The change is a
new production revision with a separate durable ledger. It does not alter or rewrite the $3 runner's 12 settled
fills and +$9.4733 realized net P&L.

The runner is restricted to `KXBTC15M`, Predictions exchange index 2, subaccount 0. Its commissioning balance is
the observed $139.4648 available after the prior runner's settled activity. No transfer is authorized or required.
The new ledger is `/data/production-market-shrunk-half-kelly-cap5-001` and starts with `PAUSE_ENTRIES`. Before the
pause is removed, commissioning must verify the exact cash balance, no position, no resting order, and no unresolved
order, then write a matching `COMMISSIONED.json` receipt.

The entry signal is unchanged: decisions occur once just after a completed UTC minute with 5–300 seconds left; raw
probability uses 90% 60-second and 10% 600-second variance; probability pools 75% raw model and 25% Kalshi midpoint
in log-odds space. The selected ask must be at least $0.45 and below $0.80, modeled net edge must be at least 0.005,
raw-model versus midpoint disagreement must be at most 0.075, binary spread must be at most $0.02, and edge must
remain nonnegative after a two-cent adverse-price buffer and fee.

Sizing is one-half of full Kelly using current Predictions cash, integer contracts, and fees inside a $5 all-in
maximum. Execution remains a 500 ms delayed IOC capped to displayed best-level integer depth, with one signal attempt
per market and no automatic POST retry. Filled positions are held to official settlement; early exits are disabled.
Unknown orders, foreign exposure, or a ledger/account mismatch block new entries.

Study 027 is the risk reference. On the already-viewed 838-trade Study 023 ledger, half-Kelly capped at $5 made
+$174.9101 from $100, retained +$63.8310 under two-cent adverse-price stress, was positive in four of five stressed
blocks, and had a $38.6751 maximum drawdown. Study 023 still failed its original validation drawdown and stressed
consistency gates, and Study 027 reused disclosed data. The live revision is an explicitly authorized risk pilot,
not proof of a profitable edge.
