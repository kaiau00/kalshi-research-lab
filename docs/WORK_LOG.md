# Work log

## 2026-09-14 — scope and foundation

- User approved BTC-only, $10/month Railway target, private `kaiau00/kalshi-research-lab`.
- Created fresh Desktop repository. No old bot source, credentials, or data imported.
- Verified a public current KXBTC15M market: `floor_strike`, `greater_or_equal`, explicit BRTI-average rules, and subcent price ranges are present. Use metadata, not ticker parsing or a cached spot opening value.
- Documented checkpoint plan and acceptance tests before implementation.

## Implementation and validation

2026-09-14: Implemented the recorder, hash-chained compressed SQLite store with a single-writer lock, book normalization, benchmark-average forecast, three independent simulated accounts, delayed IOC execution, reports, historical screening, protected dashboard and deployment files.

Validation: 27 regression tests pass. They cover limit enforcement, partial fills, cash/fee reconciliation, official settlement, stale/gapped inputs, book complements, duplicate index observations, accumulated settlement averages, unknown fees and fee changes during order latency, raw integrity/tamper detection, WAL backup/restore, deterministic replay, sealed holdout, forward registration, dashboard guards and RSA signing. Test-client dependencies emit two deprecation warnings; tests pass.

Public integration: 12 real BTC markets downloaded with candle data and zero download errors. The historical screen reports 5 unavailable/invalid quote samples rather than fabricating prices. This is an integration sample, not evidence for or against a trading edge.

Running-service smoke check: public metadata discovery succeeds; password is required; health is 200; data readiness without a Kalshi key is 503. A process restart preserves the event hash chain and a single experiment registration. Evidence is in `docs/validation/local-smoke.json`. No Kalshi credentials were read or installed.

Container validation: GitHub Actions successfully built the Docker image and started it with external networking disabled. The image includes the dashboard, requires authentication, passes process health, and correctly fails data readiness without a feed. [Container validation run](https://github.com/kaiau00/kalshi-research-lab/actions/runs/34920769606). Hosted commissioning remains unverified.

Hosting blocked: Railway rejected creation of the fresh project with “Usage limit exceeded. Please increase or remove the hard limit to resume resource provisioning.” No workspace spending setting or old service was changed. The user has been asked whether to leave hosting pending or resolve the limit themselves.

Remaining gates: clear the Railway provisioning block; deploy the new dedicated service and volume; add the user's Kalshi key through secret variables; audit real authenticated book/BRTI streams, account fee rounding, resource consumption and restart/recovery. These gates must pass before calling collection commissioned. No live trading code exists.
