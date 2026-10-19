# Market-Shrunk Kelly Risk Study 024

Declared on 2026-10-19 before calculating any Kelly-sized P&L. This is a read-only risk comparison on the exact
frozen Study 023 signal. It cannot change or promote the strategy, evaluate the final holdout, or submit an order.

The comparison starts from $100 and tests fixed $1 against 1/32-, 1/16-, 1/8-, 1/4- and 1/2-Kelly sizing. Kelly
uses the frozen market-shrunk modeled probability and entry price plus the one-contract fee. Every Kelly variant is
capped at $3 all-in per market. Quantities are integer and fees must fit inside the target budget. A decision is
skipped when its Kelly budget cannot afford one contract.

The exact same signal decisions, prices and outcomes are used for every variant. One- and two-cent adverse-price
tests retain each variant's base quantity. Reports include trades, skipped decisions, contracts, fees, P&L,
ex-top-three P&L, stressed P&L, drawdown, daily and block consistency, concentration, and target budgets.

Study 023 failed its frozen stressed-block and validation-drawdown gates. Therefore, even favorable Kelly results
cannot authorize the signal or establish an edge. Kelly is especially vulnerable because its growth optimum assumes
the modeled probability is calibrated; regime-dependent probability error turns Kelly into systematic overbetting.
