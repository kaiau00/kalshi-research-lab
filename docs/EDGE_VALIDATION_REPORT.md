# Candidate Study 003 edge-validation report

This read-only report turns the frozen Candidate Study 003 checkpoint into the formal proof-of-edge
scorecard. It does not modify the candidate engine, registration, signals, execution assumptions or
checkpoint, and it has no order-submission path.

The protected `/edge-validation` page and `/api/edge-validation/status` endpoint verify the candidate
checkpoint and registration checksums before calculating:

- settled trades and net P&L after modeled fees;
- P&L after removing the three largest winners and their share of all positive P&L;
- one-cent and two-cent adverse-fill results;
- positive-day share and a deterministic UTC daily bootstrap interval;
- maximum cost-basis drawdown, return on filled cost and unresolved exposure;
- Brier score and binary log loss against the unchanged adaptive baseline;
- every preregistered sample and promotion gate for each candidate.

The endpoint writes the derived result atomically to `/data/edge-validation/001/latest-report.json`. The
report records the candidate dataset, segment cursor, terminal digest, registration hash, candidate source
hash, report source hash and its own checksum. A checksum mismatch stops the report instead of silently
using altered state.

An individual candidate becomes reviewable after 20 observed forward UTC dates and 100 settlements. The
report can therefore show a partial formal review when a higher-frequency candidate reaches its sample gate
before a guarded candidate. It never chooses an automatic winner. Passing candidates still require a new
untouched validation study, and no result authorizes production orders.
