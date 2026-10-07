# Research lab rules

BTC-only research. Never add or enable live order submission without a new explicit user request. The Kalshi client exposes market-data GETs and WebSocket subscriptions only. Never reuse code from prior bots. Reusing credentials requires explicit user authorization; on 2026-09-17 the user authorized copying the existing Kalshi key pair from old Railway variables into this research-only service.

Preserve raw events and their local receipt order. Never backdate historical downloads into live replay. Never replace absent prices, thresholds, outcomes, or depth with favorable assumptions. Official results resolve positions; index averages are diagnostics and forecast inputs. Preserve incomplete/unresolved markets in reports.

All strategies use the same execution simulator. Money uses Decimal. Limit prices are ceilings, not guaranteed fills. Do not give resting orders automatic fills. Keep experiments versioned; record code, data prefix/hash, configuration, assumptions, and rejected decisions. Synthetic demonstrations must always be labeled synthetic.

Run `uv run pytest` and `uv run ruff check .` before pushing. Add meaningful regression checks for correctness failures. Do not execute old bots. Keep secrets, recordings, and private account data out of git and logs.

Railway budget target: $10/month, separate from the $100 simulated bankroll. One continuously running recorder/web process, persistent volume; bounded, on-demand replay jobs. Never change other Railway projects or workspace-wide spending limits without explicit authorization.

On September 23, 2026 the user explicitly authorized fair-value execution in their Kalshi DEMO account with $125 of practice funds and retrieving the matching key pair from old Railway variables. `src/demo_execution` remains the isolated demo-only adapter. Never substitute production credentials, data or endpoints into this adapter. Preserve durable order intents and reconcile uncertain requests before any additional order; no automatic POST retries. Keep the existing research registrations and accounts intact.

On October 7, 2026 the user explicitly authorized switching the current adaptive-volatility strategy to their real Kalshi account with a $100 bankroll and the same parameters. `src/production_execution` is the only authorized production adapter. Its scope is frozen to KXBTC15M, exchange index 2, subaccount 0, adaptive volatility, fixed sizing, a $3 all-in maximum per market, 5–300 seconds left, 4% minimum modeled net edge, 60/600-second variance windows blended 70%/30%, and IOC orders. It must use a separate durable ledger, must not compound above the $100 baseline, must not retry POSTs, and must block on uncertain requests or unrecognized account exposure. Any expansion, strategy change, or higher cap requires a new explicit user request.
