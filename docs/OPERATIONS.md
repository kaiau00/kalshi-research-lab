# Operating the research lab

## Deployment layout

One Railway service, one replica, one persistent volume mounted at `/data`. The same process serves the protected dashboard and records data. Hourly replay runs in a separate bounded subprocess (180 seconds), so CPU-heavy research does not run inside the recorder's event loop. The source code contains no live-order endpoint or method.

Create a **new** project; never deploy into the old Kalyx project. Set service variables:

| Variable | Value |
|---|---|
| `LAB_DATA_DIR` | `/data` |
| `LAB_DASHBOARD_PASSWORD` | A unique random secret, at least 16 characters |
| `LAB_MAX_STORAGE_BYTES` | `2000000000` |
| `LAB_MAX_REPLAY_EVENTS` | `2000000` |
| `LAB_REPORT_INTERVAL_SECONDS` | `3600` |
| `LAB_SEGMENT_EVENTS` | `250000` |
| `LAB_SEGMENT_SECONDS` | `900` |
| `LAB_ARCHIVE_GZIP_LEVEL` | `6` |
| `LAB_REMOTE_CHECKPOINT_EVERY_SEGMENTS` | `4` |
| `KALSHI_API_KEY_ID` | Your key ID, when commissioning the authenticated feeds |
| `KALSHI_PRIVATE_KEY_PEM` | Your PEM private key as a secret variable; B64 is an alternative |

Deploy the committed source using the supplied Dockerfile and `railway.json`, attach the volume **before** first startup, and disable service sleeping. Generate a Railway HTTPS domain. Username is `lab`; secrets must never be committed, pasted into GitHub issues, or copied from an old bot.

The app registers default experiment settings and a source hash when the empty data store starts. Public metadata can be recorded before the key arrives. Key changes restart the service; the volume retains the registration and raw data. For a changed strategy or codebase, stop collection, preserve/export the old database, and choose a new `LAB_DATA_DIR` on the same volume. Do not delete old raw data to reset a test.

## $10/month target

Railway meters actual CPU, memory, volume and network use. One small process and SQLite avoid a separately billed database. Initially consider 256 MB memory and 0.1 vCPU **only after verifying those limits against measured peak memory and collector lag**. If replay cannot run reliably within that allowance, run less frequent or offline replay rather than silently increasing spend. The project budget is a target, not a service-level dollar cap.

Check actual Railway usage during commissioning and again after one day. The segmented recorder seals at 250,000 events or 15 minutes, uses gzip level 6, writes its durable local checkpoint after every segment, and rotates two remotely verified checkpoint slots every fourth segment. Raw archives still upload for every segment. These settings reduce repeated work without sampling or discarding observations. Storage and replay limits remain explicit safety stops, not a long-term archival strategy.

Workspace spending limits affect other projects. Do not raise or remove them without a separate user decision. On 2026-09-14, project creation was rejected by Railway because the existing workspace hard usage limit had been reached. No new service, volume, or successful deployment was created by that attempt.

Sources: [Railway cost control](https://docs.railway.com/pricing/cost-control), [resource prices and measurement](https://docs.railway.com/guides/right-size-cpu-memory).

## Commissioning checklist

1. Verify the deployment reaches `SUCCESS`, `/healthz` is 200, and the dashboard requires authentication.
2. Before credentials, expect `waiting_for_credentials` and `/readyz` 503.
3. After the user adds a key, confirm authenticated BRTI **and** order-book snapshots; `/readyz` should become 200 when both are fresh. Subscription access may depend on the account; do not silently substitute another price source.
4. Capture at least two complete BTC markets, inspect their thresholds against market rules, audit source/receipt timestamps, sequence resets, final-minute observations, and official outcomes.
5. Run the registered forward comparison, inspect every initial order and settlement manually, and check fee assumptions against the actual series/account.
6. Restart once and verify unchanged raw prefix hashes, no duplicate settlements in deterministic replay, and continued collection on the volume.
7. Check resource metrics and confirm the monthly estimate fits the budget. Only then call unattended collection commissioned.

The authenticated feed, fee/account details, deployment lifecycle, and real resource usage cannot be certified from a synthetic test. This build includes regression tests, not a claim of being bulletproof.

## Failure behavior and recovery

- Missing credentials: public metadata continues; book/BRTI recording waits.
- Disconnect, sequence gap, malformed book or local clock regression: invalidate the book; new valid snapshots are required. Raw events stay available for audit.
- Stale book, benchmark, missing official threshold or missing final-minute samples: reject a simulated entry.
- Missing official outcome: keep the position and locked capital unresolved.
- Storage cap: stop the collector, make health fail, and retain the existing store. Export before increasing storage or starting a new dataset.
- Replay timeout/size cap: report the failure; collector continues. Increase offline capacity deliberately.
- Code/config mismatch: forward report refuses to run. Exploratory train/validation replay is still available and must not be relabeled prospective.

Use `research-lab backup --db data/events.sqlite3 --output exports/frozen-01.sqlite3` to export a consistent snapshot and verify its event hash chain. This uses SQLite's backup API and refuses to overwrite a file. Copying only the `.sqlite3` file while WAL writes are active can lose committed data. Store the exported snapshot and verification output outside the Railway volume. A WAL backup/restore regression test passes locally; Railway volume recovery and automated external backup still require commissioning before long-duration unattended research.
