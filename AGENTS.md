# Research lab rules

BTC-only research. Never add or enable live order submission without a new explicit user request. The Kalshi client exposes market-data GETs and WebSocket subscriptions only. Never reuse code from prior bots. Reusing credentials requires explicit user authorization; on 2026-09-17 the user authorized copying the existing Kalshi key pair from old Railway variables into this research-only service.

Preserve raw events and their local receipt order. Never backdate historical downloads into live replay. Never replace absent prices, thresholds, outcomes, or depth with favorable assumptions. Official results resolve positions; index averages are diagnostics and forecast inputs. Preserve incomplete/unresolved markets in reports.

All strategies use the same execution simulator. Money uses Decimal. Limit prices are ceilings, not guaranteed fills. Do not give resting orders automatic fills. Keep experiments versioned; record code, data prefix/hash, configuration, assumptions, and rejected decisions. Synthetic demonstrations must always be labeled synthetic.

Run `uv run pytest` and `uv run ruff check .` before pushing. Add meaningful regression checks for correctness failures. Do not execute old bots. Keep secrets, recordings, and private account data out of git and logs.

Railway budget target: $10/month, separate from the $100 simulated bankroll. One continuously running recorder/web process, persistent volume; bounded, on-demand replay jobs. Never change other Railway projects or workspace-wide spending limits without explicit authorization.
