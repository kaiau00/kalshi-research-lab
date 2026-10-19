# Market-Shrunk Half-Kelly Production 001

Authorized by the user on 2026-10-19. This revision trades the exact Study 023 lead with the Study 024 half-Kelly
risk rule. The authorization is a deliberate live pilot; it does not change the research conclusion that Study
023 failed its validation drawdown and stressed-period consistency gates.

The runner is restricted to `KXBTC15M`, exchange index 2 and subaccount 0. A fresh ledger starts with a durable
`PAUSE_ENTRIES` file and requires exactly $100.0000 of index-2 cash before its first order. It never transfers
funds. The previous production ledgers remain immutable.

At the first processing opportunity just after each completed UTC minute, from 5 through 300 seconds before
market close, it computes the structural probability with 90% weight on 60-second variance and 10% weight on
600-second variance. It then pools that probability with the Kalshi midpoint at 75%/25% in log-odds space. The
selected side must cost at least $0.45 and less than $0.80, have at least 0.5 percentage points of modeled net
edge after the one-contract fee, remain nonnegative after adding two cents and recalculating the fee, differ from
the raw structural probability by at most 7.5 points, and have a binary spread no greater than two cents.

For a qualifying decision, full Kelly is `(p - c) / (1 - c)`, where `p` is the pooled selected-side probability
and `c` is the selected-side price plus the one-contract fee. The target budget is current index-2 cash times
one-half of full Kelly, capped at $3. Quantities are integer and their total price plus fee must fit within the
target. A budget below one contract is skipped.

Each market receives at most one signal attempt. The runner waits 500 ms, rechecks the live best eligible level,
caps quantity to displayed integer depth, and submits one IOC order without an automatic POST retry. Unknown order
state, a resting order, unrecognized exposure, or a position mismatch blocks further entries. Filled positions
are held to Kalshi's official settlement; early exits are disabled.

Study 024's half-Kelly path made +$106.6278 in the exposed historical sample but reached the $3 cap on 829 of 838
decisions and had a $27.0156 maximum drawdown from $100. This is the expected risk reference, not a forecast.
