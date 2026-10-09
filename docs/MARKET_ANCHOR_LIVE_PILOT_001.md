# Market Anchor live pilot 001

On October 9, 2026, the user authorized a real-money pilot of the frozen Market Anchor candidate before its
prospective promotion gate completed. The pilot is experimental. Its retrospective results do not establish a
profitable edge, and the independent Study 005 prospective collection continues unchanged.

## Frozen production scope

- Strategy: `market_agreement_band_001`
- Source signal: adaptive volatility with at least 4% modeled net edge after fees
- Series: `KXBTC15M`
- Exchange index: 2; subaccount: 0
- Entry window: 5–300 seconds before close
- Decision-time selected-side ask: at least $0.30 and below $0.95
- Absolute raw-model YES probability versus Kalshi two-sided midpoint gap: at most 0.08
- Binary spread: at most $0.02
- Sizing: fixed, with a $1 maximum all-in entry cost per market
- Execution: 500 ms delayed IOC against a fresh, still-marketable book
- Position management: hold to Kalshi's official settlement; early exits disabled
- Capital baseline at authorization: $57.9544 cash on exchange index 2
- Configuration revision: `market-anchor-production-001-20261009`
- Risk revision: `market-anchor-fixed-risk-001-20261009`
- Hold revision: `market-anchor-hold-settlement-001-20261009`

The pilot uses `/data/production-market-anchor-001/orders.sqlite3`. The completed adaptive production ledger at
`/data/production-adaptive-001/orders.sqlite3` remains unchanged.

## Safety behavior

Before every order, the runner verifies exchange availability, available cash, no foreign account exposure, no
resting order, a fresh book, and that the original decision-time limit remains marketable after 500 ms. It writes
the order intent durably before the POST, never retries an uncertain POST, and blocks later entries until the exact
client order ID is reconciled. Only one open position can exist at a time. Every fill is compared once per second
with the signed Kalshi position and held until official settlement.

To match the retrospective filter exactly, every underlying adaptive signal consumes the same 500 ms simulated
arrival attempt even when Market Anchor rejects it. If that rejected raw attempt would have filled, the market is
durably marked filtered out and cannot be reconsidered. If it would have canceled, it counts toward the same
three-attempt limit and ten-second retry interval as the research engine. Accepted orders are capped to the
integer quantity visible at the best arrival level before submission.

## Evidence boundary

The candidate earned +$13.6701 in its ten-day development window and +$8.1592 in a later ten-day retrospective
window. The later window passed aggregate P&L, concentration, and two-cent stress checks but was positive in only
three of five chronological blocks. Both windows were visible before live authorization. Live results and Study
005 prospective results must be reported separately.

## Deployment

Railway deployment `2cb2d5bc-8f49-4f5c-bc3b-8301901b1c79` reached `SUCCESS` with image digest
`sha256:ea315c1c6ea9ab131774f64a7dac702ebb1f4e9db3e118adad5fbc651e741849`. Initial verification reported
`watching`, the exact candidate registration hash, $57.9544 cash, no position, no unresolved order, and zero
Market Anchor attempts or fills. The completed adaptive ledger and new Market Anchor ledger both existed on the
persistent volume. The daily monitor was updated to watch this revision and its live milestones.

The attempt-fidelity fix was deployed as `e074c389-ed67-4150-a991-ecf98c8bbc9d` with image digest
`sha256:9d661ee1eb5b29dbbd72113370bb71dad8e3daa00708792a045e5c2c5f8af78e`. It reached `SUCCESS` while entries
were temporarily paused. Verification showed zero fills, zero submitted orders, no position, no unresolved order,
and no runtime error. The temporary pause was then removed and the corrected runner returned to `watching`.
