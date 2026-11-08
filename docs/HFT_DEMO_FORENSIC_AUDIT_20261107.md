# HFT Demo forensic audit — 2026-11-07

This is a read-only operational audit of the isolated Kalshi Demo Study 029
runner. It is not an HFT performance result and does not authorize a Demo or
production order.

## Trigger

The Demo runner stopped on October 26 after the cancellation read for one
post-only `NO` quote returned HTTP 404. Its durable journal therefore retained
the order in `uncertain_cancel` and correctly refused to continue quoting.

## Independent evidence collected on November 7

The journal's last authoritative order snapshot records all of the following:

- the quote was for `KXBTC15M-26OCT261030-30`;
- the original fill count was zero; and
- the order was still recorded as resting immediately before its cancellation
  read returned HTTP 404.

Using the isolated Demo credential, read-only signed API calls then showed:

- the specific order endpoint still returns HTTP 404;
- the ticker-level order list contains only the separate executed `YES` fill,
  not this `NO` quote;
- the account has no resting orders; and
- the account has no nonzero position.

That satisfies the narrow evidence required by
`Runner.confirm_missing_cancel`: a zero-filled quote is absent from its ticker
orders and cannot have produced a remaining position. The original safety stop
was therefore correct, and the old cancellation can be closed by the runner's
existing durable reconciliation path.

## Deliberate non-action

No ledger record was changed, no cancellation was submitted, and the service
was not restarted. A normal service restart would both run reconciliation and
resume Demo quoting because `PAUSE_QUOTES` is absent. Those are separate
external actions requiring explicit authorization.

## Next safe repair

Before restarting, add a durable pause control or a dedicated
reconcile-only startup mode. Then restart only to obtain the durable
reconciliation receipt, verify zero Demo resting orders and zero positions,
and leave quoting paused. This is an execution-harness repair only; Study 029
still has no credible economic edge.
