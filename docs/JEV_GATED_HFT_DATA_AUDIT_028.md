# Study 028 data-readiness audit

Read-only audit performed on 2026-10-22. No deployment, variable, production strategy, order, archive object or
volume file was changed.

## Available evidence

- Railway `Kalyx / production / research-lab` was running a successful deployment.
- The READY `/data` volume used 3,666.59 MB of its 5,000 MB allocation.
- The private `research-archive` bucket held 10,319 objects totaling 38.4 GB.
- The v6 catalog contained 8,059 segments: 8,056 archived, two sealed and one open.
- Sealed/catalogued prefixes represented 1,275,153,752 events and 32,471,410,419 compressed archive bytes.
- A representative recent 500,000-event segment contained 498,691 order-book deltas, two book snapshots, 693
  BRTI messages and two subscription acknowledgements.

This is unusually rich event-level evidence for studying fair value, quote changes, latency stress and future
markout. It is far stronger than the six-month minute-candle archive for intramarket timing.

## Blocking limitation

The v6 collection profile deliberately omitted Kalshi's public trade channel because the existing strategies used
delayed IOC execution. Consequently, the archive cannot show which displayed size was actually transacted, infer
our place in queue, or prove that a resting maker order would have filled. Order-book deltas alone mix trades,
cancellations and new size and cannot safely be relabeled.

The existing archive is therefore **ready for Stage 1 signal and markout research** and **not ready for maker-fill
or maker-P&L claims**. A separate forward tape with public trades and the current event channels is required before
the market-making hypothesis can pass Study 028.

## Cost implication

The current archive is already 38.4 GB and the volume is about 73% full. Adding a high-rate channel to the current
profile without first measuring and budgeting it risks the $10 Railway ceiling and the remaining volume reserve.
The next recorder change must use a separate registration, measure event and compressed-byte rates, and set a
hard storage/billing stop. It must not silently modify the existing v6 dataset.

The local forward recorder and two live read-only measurements are documented in
[HFT forward-tape commissioning](HFT_FORWARD_TAPE_028_COMMISSIONING.md). They show that continuously duplicating
the book would be wasteful; the recommended hosted design is an incremental trade-only sidecar.
