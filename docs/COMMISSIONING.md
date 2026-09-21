# Collection and replay commissioning — September 18, 2026

The corrected collector and bounded replay passed the data commissioning checks. This validates the research inputs and archive/replay mechanics; it does not establish profitable strategies, executable fills, or proven parameters.

## Evidence

- Dataset `6907fda78df14d2fb2c182a1107396a0` in `/data/segments-v3` recorded 33,631,516 events by the overnight check, archived 340 segments with zero backlog, and retained about 31 MB locally. The old SQLite datasets remain intact.
- Restored segments 0–11 from verified private bucket objects: 1,197,032 events, exact archive checksums and event chains, no malformed frames, no in-session sequence breaks, and no clock adjustments. Four startup markers precede the two fully covered markets.
- `KXBTC15M-26SEP171345-45` and `KXBTC15M-26SEP171400-00`: each has 900/900 benchmark seconds, all 60 settlement-window seconds, and valid book reconstruction for all 900 seconds. Snapshots arrived before open. Threshold metadata arrived about 0.92 and 1.39 seconds after open; it was never backdated.
- Reconstructed official settlement prices are 76696.72 and 76608.90, respectively. Both match recorded and independently fetched finalized official outcomes exactly using `[close-60s, close)`.
- Fresh two-sided liquidity covered 826.06 and 843.32 seconds. Empty/one-sided books are retained as observed and are not assumed tradable.
- The overnight checkpoint checksum, source registration, total replayed event count, reservation totals, shared pending/position references and unique settlement tickers passed consistency checks. This is an accounting continuity check, not a fill realism audit.
- See [sanitized audit](validation/segmented-commissioning.json). Partial startup and end-of-prefix markets are explicitly retained in the evidence.

## Capacity and cost

The six-hour pre-optimization measurement averaged 0.1002 vCPU and about 133 MB RAM. Egress was 1.1100 GB over 361 one-minute samples, about 133 GB/month if repeated. That suggested roughly $11/month and exceeded the target.

The compact archive omits only redundant per-event digest strings: every original event field remains present and each digest is exactly reconstructible. A real 100,000-event archive shrank from 7,721,627 to 3,084,840 bytes (60.05% smaller), with an identical reconstructed terminal hash. Both archive formats and modified-payload rejection have regression coverage. The new source is registered separately in `/data/segments-v4`; v3 evidence is not mislabeled as a v4 forward test.

At similar load, the smaller uploads suggest roughly **$7–9/month** including compute, memory, volume and retained archives. This is a conditional planning estimate, not a guarantee or an observed full-month bill. The CPU/RAM measurement predates this archive change; traffic, checkpoint history and job demand can vary. Current resource prices are $20/vCPU-month, $10/GB-month RAM, $0.05/GB egress and $0.15/GB-month volume; bucket storage is $0.015/GB-month and uploads incur service egress. Hobby includes $5 usage within its $5 minimum. Sources: [Railway plans](https://docs.railway.com/pricing/plans), [bucket pricing](https://docs.railway.com/storage-buckets).

The existing $10 workspace hard usage limit is unchanged. Local data remains capped at 512 MB with a 300 MB free-volume reserve. The new dataset's archive cap is 60 GB, giving headroom over the approximate 39 GB/month compact raw rate; older archives remain separately retained. Limits stop collection safely rather than erase evidence. This is finite capacity, not indefinite retention.

The deployed v4 format also passed a direct bucket read-back: its first 100,000-event archive was 3,142,355 bytes, used five-field envelopes, and reproduced the recorded terminal hash and original source registration. The checkpoint checksum/source both matched and next segment was 1. See [live compact-format evidence](validation/compact-archive-live.json). GitHub CI, including the production image check, [passed](https://github.com/kaiau00/kalshi-research-lab/actions/runs/35348396368).

## Remaining before strategy review

1. Completed for the initial sample: independent fill/accounting audit and six execution scenarios; see [EXECUTION_AUDIT.md](EXECUTION_AUDIT.md). Event fee recording and inactive-market guards added in v5. Account-specific and actual multi-fill behavior remain qualified.
2. Compare registered strategies across independent time periods and market conditions; select parameters using development data only.
3. Freeze selected settings and assess untouched/forward evidence, drawdown, trade count and sensitivity with separate $100 simulated accounts.
4. Re-measure sustained compact-format costs. Full recovery after loss of the entire volume/catalog is a separate untested gate; normal archive restore has passed.

All 44 automated tests pass and Ruff is clean. No live order submission exists. No strategy or parameter is presently proven profitable.


## September 20 follow-up

Fee capture and execution diagnostics are documented in [EXECUTION_AUDIT.md](EXECUTION_AUDIT.md). The v5 recorder stayed healthy for over two days, accumulating more than 95 million events and 981 verified archives with zero backlog and reconciled account checkpoints. The first live v5 archive was independently downloaded and hash-verified. A CI-only failure revealed a real initial-poll timing assumption; explicit first-request state fixes it and passes 58 tests plus the container check.

The full-day measurement averages about 0.101 vCPU and 0.169 GB RAM, with 2.35 GB service egress/day. At those rates, including volume and a $1 archive allowance, the planning estimate is approximately $8.6/month. This supersedes the earlier size-only estimate but remains conditional on future workload and growing account/checkpoint history. [Usage evidence](validation/usage-2026-09-20.json). The $10 workspace hard usage limit remains unchanged.
