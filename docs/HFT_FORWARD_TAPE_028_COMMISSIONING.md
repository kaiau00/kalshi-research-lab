# HFT forward-tape local commissioning

Completed locally on 2026-10-22. The command used existing Railway-provided research credentials for read-only
Kalshi WebSocket authentication and wrote only temporary local SQLite files. It did not deploy code, change a
Railway variable, call a portfolio endpoint, submit an order or call Jev.

## Recorder behavior

The bounded `hft-record` command records `orderbook_delta` and `trade` on the same Predictions WebSocket
connection, plus BRTI on the authenticated benchmark connection. It preserves raw frames, local receipt order,
exchange timestamps, stream/session identity, gaps, market metadata, fee metadata and official outcomes in a
SHA-256 event chain. The command refuses an existing output path, accepts only explicit `KXBTC15M` subscriptions,
has a hard byte limit and exits after 10–1,800 seconds.

Trade validation requires the documented ID, complementary YES/NO price, fixed-point quantity, taker outcome and
book side, block marker and exchange millisecond timestamp. Block trades remain recorded but cannot advance a
displayed-queue simulation.

Kalshi returned code 12 when the first prototype sent multiple subscription IDs in one update request despite the
general connection schema supporting an SID array. The implementation now sends one update per channel SID. A
fresh capture completed with no error or reconnect frame.

## Measured captures

| Capture | Events | Public trades | Duplicate trade IDs | Compact Zstandard size | Errors |
|---|---:|---:|---:|---:|---:|
| 120.05 seconds | 93,857 | 4,149 | 0 | 1,601,301 bytes | 1 update error, corrected afterward |
| 60.05 seconds | 61,483 | 2,437 | 0 | 1,064,310 bytes | 0 |

The corrected capture's terminal event-chain digest was
`528e55f78cf353ecf022a2c8e9a5650c3103cae7d04fa65db5b2d60ffd98efd0`.

The corrected one-minute sample projected the following retained compact data if its unusually short window were
representative for 30 continuous days:

| Component | Projected 30-day size |
|---|---:|
| Existing order-book stream | 41.17 GB |
| New public-trade stream | 3.69 GB |
| BRTI | 0.11 GB |
| Registration, metadata and control frames | 0.18 GB |
| Combined duplicate recorder | 45.94 GB |

The two samples put the incremental public-trade stream at roughly **3.2–3.7 GB per 30 days**. This is a rate
estimate, not a quota promise; BTC activity varies and a 24-hour commissioning sample is still required.

At Railway bucket storage pricing of $0.015/GB-month, one newly retained month of trades adds roughly $0.05–$0.06
to the steady-state storage line for that month's data. Retaining every month accumulates that storage. Upload
egress, CPU and volume use are separate, so the $10 total ceiling still requires an observed Railway billing check.

## Hosted sidecar implementation

The cost-controlled hosted implementation is now complete locally and remains disabled. It subscribes only to
the public `trade` channel for the main recorder's explicit current `KXBTC15M` watch set. It does not duplicate
the book or BRTI, import an account client, expose an order method or call Jev.

The sidecar writes a separate receipt-ordered segmented dataset under `/data/hft-trades-v1`. Its registration
freezes the Study 028 hash, source hash, channel, BTC scope, no-order authority, block-trade rule and conservative
cross-stream join rule. Raw WebSocket frames retain the trade ID, fixed-point price and quantity, exchange time,
local receipt time, stream sequence and session. A bounded recent-ID cache reports immediate duplicates without
allowing memory to grow with the full tape.

Every sealed segment is hash-verified, compressed and uploaded under a private `hft-trades-v1/` bucket prefix.
The upload is read back by the existing bucket verifier. A durable manifest is uploaded before the local segment
is marked archived and deleted. Upload or manifest failure leaves the local segment sealed for an exact retry;
the generic restore path reconstructs and verifies the original event chain.

Two independent stops bound the experiment:

- `LAB_HFT_TRADE_HOT_MAX_BYTES=256000000` stops capture before the sidecar can consume the remaining volume.
- `LAB_HFT_TRADE_ARCHIVE_MAX_BYTES=5000000000` stops capture once the new archive reaches 5 GB and preserves the
  unarchived local segment.

The trade tape rotates independently from the main recorder at 100,000 events or five minutes, whichever comes
first. This keeps a normal open segment well below the 256 MB hot limit even when the public trade feed is much
busier than the commissioning smoke sample. The optional controls are
`LAB_HFT_TRADE_SEGMENT_EVENTS` and `LAB_HFT_TRADE_SEGMENT_SECONDS`; changing them requires a new commissioning
review.

`LAB_HFT_TRADE_TAPE_ENABLED` defaults to `0`. Sidecar startup or runtime failure is isolated from the production
runner and is visible at the protected `/api/hft-trade-tape/status` endpoint. It adds no Railway instance.

The reviewed implementation source identity is
`63e83d76c3e5a7ffd59179f660676e2349aced4728f4b496aa414d75f6edcb00`. A 30-second read-only smoke test of the
preceding capture implementation
(`2fc3187a8bb955f0dfb021954bbac3ad75f593b75232e99b36ceea745dbfac5f`) against two current Predictions markets
captured 790 valid non-block public trades, one subscription
frame and one session-gap marker: 793 events total. The complete temporary segmented chain verified, with zero
invalid frames, duplicate IDs, WebSocket errors or block trades. The test used Railway-provided credentials only
for WebSocket authentication and did not deploy or call an account or order endpoint.

## Reviewed deployment sequence

1. Verify the current live runner, cash, exposure, unresolved-order count, recorder/archive state and Railway
   usage immediately before deployment.
2. Deploy the reviewed tree to the existing service with the sidecar still disabled and verify production is
   unchanged after the restart.
3. Set the four documented sidecar variables, enable only the trade tape and restart once.
4. Verify the Study 028 and source hashes, BTC-only subscription, zero order authority, archive prefix, both hard
   caps and healthy production status.
5. Observe 24 hours of event count, compressed bytes, volume growth, archive backlog, CPU, memory and Railway
   usage. Disable the sidecar if the measured path threatens the $10 monthly ceiling.
6. If the 24-hour audit passes, collect the frozen 20-date tape. Do not evaluate maker P&L, call Jev or change the
   live strategy during this commissioning step.

Enabling the sidecar requires a deployment restart and Railway variable changes, so it remains a separate
reviewed operation.

## Hosted commissioning result

Study 028 was enabled on the existing Railway research service on 2026-10-22 with production execution disabled.
The first live-rate check showed that the shared 500,000-event/30-minute segment policy could reach the 256 MB
hot limit before rotation. The sidecar was therefore moved to its own reviewed source identity and a fresh dataset,
with rotation fixed at 100,000 events or 300 seconds. This change did not alter the main recorder, a strategy, an
account path or an order path.

Deployment `4d3876c1-dca8-4d40-988c-31a261b2cc1e` then verified the complete hosted path. At the recorded checkpoint:

- process health returned HTTP 200 and the main book and benchmark recorder remained connected;
- production status was `disabled`;
- both production and demo order authority were false;
- 598,577 public trades had been recorded with zero invalid messages and zero duplicate trade IDs;
- 36 segments totaling 47,604,889 compressed bytes had been verified and archived;
- the local hot dataset used 6,659,092 bytes, with zero sealed backlog; and
- the configured 256 MB hot cap and 5 GB archive cap were reported by the running service.

This proves continuous capture, time/event rotation, bucket upload, read-back verification, manifest update and
local cleanup. It does not prove the maker strategy or authorize Jev, demo orders or live orders. The remaining
commissioning gate is the planned 24-hour cost and resource audit before treating the tape as a long-running data
source.
