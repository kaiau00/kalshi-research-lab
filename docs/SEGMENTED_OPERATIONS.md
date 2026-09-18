# Segmented recording and recovery

The current design uses one continuously running Railway service, the existing volume, and a private Railway bucket. Existing `/data/events.sqlite3` and `/data/normalizer-v2/events.sqlite3` are preserved. The current dataset uses `/data/segments-v4`; `/data/segments-v3` and its archives are also preserved. The collector/model was validated on v3; v4 changes only the lossless archive envelope.

## Data and execution boundaries

The recorder stores every subscribed order-book and BRTI frame unchanged in receipt order. Public-trade subscriptions are omitted from this experiment because none of the three strategies or the IOC execution model uses them. This is a new collection profile and source registration, not a retroactive change to earlier data.

SQLite segments seal after 100,000 events or five minutes. Each sealed prefix has its own event hash chain; each following segment begins with its predecessor's terminal hash. A catalog identifies the dataset, segments, official metadata and verified archive objects. Open-book and benchmark memory continue across segment boundaries.

A separate subprocess handles one sealed segment per maintenance job, with the existing 180-second limit. It verifies every event, advances the same three simulated accounts, and saves an atomic JSON checkpoint. Cash, reservations, positions, pending-order identity, historical decisions, benchmark history, books and subscription sequences survive checkpoints. Only the first segment contains the original experiment registration; later segments cannot reset the bankroll. Matching source/config is required on every resume.

The worker exports event IDs, receipt/source timestamps, kind and unchanged payloads to gzip JSONL. The per-event digest is reconstructed exactly from these fields and the previous digest; the terminal digest remains in the catalog and object key. Readers accept both the older six-field envelope and the compact five-field envelope and reject count/hash mismatches. The worker uploads to the private bucket, then downloads and hashes the complete object. A compressed recovery checkpoint is also uploaded and verified. Only then does it mark the segment archived and remove the redundant hot SQLite file. Upload failure preserves the local data. Retry after checkpoint publication skips already-processed events. Two alternating checkpoint objects bound remote checkpoint retention; raw archive objects are never expired automatically.

## Bounds and budget

- Local dataset safety threshold: 512 MB, including checkpoints and reports.
- Free-volume reserve: 300 MB. Old datasets are outside the new directory but still consume real volume space, covered by this reserve.
- Raw archive quota: 60 GB per current dataset; reaching it fails maintenance and eventually stops collection at the local threshold rather than discarding data or increasing spending.
- Five latest derived reports retained; raw observations and current account history remain preserved.
- Existing workspace $10 hard usage limit is unchanged. This is a budget constraint, not a promise that recording can continue indefinitely regardless of throughput.

Railway buckets cost $0.015/GB-month; bucket API operations and downloads are free, but uploads count as service egress. A full 60 GB raw archive costs about $0.90/month for storage, plus upload traffic, CPU, RAM, volume and small checkpoint overhead. The September 18 measured load and compact-format experiment suggest roughly $7–9/month, conditional on similar traffic; this is not a measured month of billing. Earlier archives also continue to incur storage. See COMMISSIONING.md. [Railway bucket pricing](https://docs.railway.com/storage-buckets).

## Rollover and outcomes

BRTI has its own WebSocket connection and continues during periods without active BTC markets. Book subscriptions are updated in place; metadata discovery includes upcoming markets and polls every second near boundaries (five seconds otherwise). Available future books are subscribed before their market opens. Resolution runs separately, retains `determined` contracts until `finalized`, and records observed result revisions. The simulator pays positions only after a finalized official outcome is received.

A benchmark reconnect clears its benchmark history for warmup; a book reconnect invalidates books without resetting BRTI history. Missing observations remain missing. Protocol acknowledgment messages consume their sequence numbers even though they do not change book levels.

## Restore and audit

Use `research-lab restore-segments --root /data/segments-v4 --output /tmp/frozen-validation.sqlite3` to restore all sealed segments to a new SQLite file. The output path must not exist. The restore holds the maintenance lock to prevent races with hot-replica removal, checks object checksums and every archived event hash, verifies segment linkage, and rebuilds a fresh global event chain while preserving payloads and receipt/source times. It excludes the still-open segment; allow a subsequent seal before expecting the latest result in the restored prefix.

Run `PYTHONPATH=src python scripts/audit_data.py --db <restored-file>` for complete data coverage/settlement checks. The restored chain differs from segment-local chains because IDs/segment scope differ; retain catalog/archive hashes as provenance. Downloaded later official data is reference evidence, never backdated into these recordings.

For catastrophic volume recovery, retrieve the raw objects and latest valid checkpoint slot using the bucket credentials, verify their hashes and segment-header links, and reconstruct a catalog before resuming. The current automated restore uses the existing catalog. Full bare-volume disaster recovery is a separate commissioning gate; do not claim it has been tested merely from a normal archive restore.

## Failure response

A failed archive, checkpoint mismatch, corruption, capacity limit, lost stream, or unfinished finalization is visible in status or validation results. Fix the cause and preserve the data. Never clear checkpoints or registrations to make a forward replay pass. Source/config changes require a fresh dataset. Infrastructure limits must not be raised without revisiting the budget.
