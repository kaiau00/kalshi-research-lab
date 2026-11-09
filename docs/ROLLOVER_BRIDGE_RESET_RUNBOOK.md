# Rollover Bridge Study 007 — reset-day runbook

This runbook prepares the already registered, read-only Study 007 development
replay. It does not authorize a Demo or production order, change an existing
strategy, or permit parameter selection outside the frozen protocol.

## Frozen scope

- Dataset: `e2d5cb33e7c44660809b531f03d4b4e3`
- Seed segment: 4,345, from digest
  `cf620d41eb95df0912d1a26ec1708d9545a821dbb3a3442647f09bab8055f786`
- Terminal segment: 7,540, with digest
  `aab571dfb5ee829b2fe3f00a06af8ce0cd7d7494e4319ff563e7848b4f44aab4`
- Expected source: 3,196 archived segments, 591,327,720 receipt-ordered
  events and approximately 14.341 GB of compressed archive reads.
- Execution assumptions: four opening offsets (5/15/30/60 seconds), 500 ms
  arrival, fresh two-sided book only, displayed-depth IOC accounting, official
  settlements, supported fees, $1 maximum all-in cost, and one entry per
  market.

The runner verifies the checksum and digest linkage of every downloaded
segment, checkpoints every ten segments, deletes its temporary archive after
verification, and refuses a changed registration, seed or predecessor digest.

## Cost gate

The previous billing period reached $9.5284 against the $10 hard limit on
November 8, 2026. Do not run this replay before the next reset.

At the reset:

1. Confirm current Railway usage is below $1 and the $10 hard limit is still
   present.
2. Confirm both paused trading controls still exist: the live
   `PAUSE_ENTRIES` ledger control and HFT Demo `PAUSE_QUOTES` control.
3. Start only the `research-lab` service. Do not start `hft-demo`.
4. Verify the research service is healthy while the live runner reports
   entries paused and no exposure.

## Bounded replay

Run the existing `scripts/run_rollover_study.py` in **at most 100-segment
batches**. After each batch, read the JSON result and confirm that:

- `next_segment` only advances from the prior verified checkpoint;
- the reported digest remains on the frozen chain;
- the durable checkpoint is present; and
- Railway usage remains below the hard limit.

Stop immediately for an archive checksum, predecessor-digest, registration,
checkpoint or processing error. Do not skip a segment, alter an input,
increase the batch limit, or substitute newer archive data.

## Completion decision

Once the terminal segment is reached, preserve the full machine-readable
development report and inspect every protocol gate: sample size, Kalshi-versus-
model forecast score, base and one-/two-cent-stressed P&L, winner
concentration, daily and five-block consistency, drawdown, calibration,
latency stress and unresolved exposure.

A development pass does **not** authorize trading. It only permits freezing one
new candidate and beginning a separately registered untouched forward study.
