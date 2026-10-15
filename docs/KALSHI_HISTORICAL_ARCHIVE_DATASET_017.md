# Kalshi Historical Archive Dataset 017

Declared on 2026-10-15 before using the expanded archive for any strategy result. This is a read-only data
acquisition. It cannot submit an order, authorize a strategy or convert historical candle observations into
claimed fills.

## Sources and interval

- Series: `KXBTC15M` only.
- Requested interval: 2026-04-15 00:00:00 UTC inclusive through 2026-10-15 00:00:00 UTC exclusive.
- Official market metadata comes from Kalshi's current and historical market listings. It supplies the exact
  target, official result and expiration value.
- One-minute Kalshi contract candles come from the public batch candlestick endpoint while a market remains in
  the current data set and from the dedicated historical-market endpoint after archival. They contain YES bid
  and ask OHLC, trade-price OHLC, volume and open interest.
- Exact BRTI history comes from Kalshi's authenticated CF Benchmarks passthrough using the frozen `BRTI`, `HOUR`
  query. Each response preserves all official observations for one UTC hour. BRTI can publish at 200 ms; the
  settlement audit uses only top-of-second ticks, matching the standard 60 observations in Kalshi's final minute.

Raw responses are stored in local, ignored SQLite files in receipt order with the repository's SHA-256 event
chain. The downloader is resumable only when the requested interval and acquisition registration match exactly.
The already authorized production API key authenticates only the whitelisted market-data GETs and benchmark GET
so the acquisition uses Kalshi's account read-rate buckets. No private account or order endpoint is used, and the
key material is never copied into the dataset, repository or logs.

## Validation before research

The completed archive must report the number of settled markets, markets with quote candles, hourly BRTI
responses, missing responses, database size and final event-chain digest. A separate audit must verify the chain,
unique market identities, UTC coverage, official labels, quote-field validity, BRTI ordering and absence of
look-ahead joins before any strategy is evaluated.

## Completed acquisition and audit

The acquisition completed on 2026-10-15. The ignored local archive is
`data/external/kalshi/kxbtc15m-20260415-20261015.sqlite3`; its ignored machine-readable audit is
`reports/kxbtc15m-20260415-20261015-audit.json`.

- 17,311 settled markets were selected. 17,303 have one-minute candle history; Kalshi returned no candles from
  either endpoint for eight named markets recorded in the download summary.
- The archive contains 265,657 candle rows. All rows have ordered, in-range, non-crossed YES bid/ask OHLC after
  accounting for Kalshi's legacy `open`/`close` and current `open_dollars`/`close_dollars` response schemas.
- All 4,331 required BRTI UTC hours were retrieved. No hour is unordered, duplicated or outside its requested
  hour.
- The receipt chain verifies all 34,135 events through SHA-256 digest
  `03526f0e63396de6cd8ddf8df77bcddbd83aff4d0753daf3f4b5285232b7c70f`.
- Of the markets with a numeric official expiration and 60 top-of-second settlement observations, 17,164
  reconstruct exactly and 17,286 reconstruct within one cent. There are 122 one-cent rounding differences, two
  material metadata-versus-history discrepancies, 20 markets with an incomplete 60-second BRTI window and three
  markets without a numeric official expiration value.
- Kalshi omitted the target/strike rule from 24 unique archived market records labeled `Target price: TBD`.
  Those result rules remain explicitly unverifiable. Every official YES/NO result with enough metadata to check
  agrees with the settlement value and strike.

The two material settlement discrepancies and every missing/unverifiable ticker remain in the audit report and
must be excluded or handled by a frozen rule before strategy evaluation. No value was filled or corrected.

## Interpretation limit

Minute bid/ask candles do not contain displayed depth, queue position, exact 500 ms arrival quotes or the path
inside a minute. They can support signal and conservative quote screening. They cannot by themselves establish
that an IOC order would have filled. Any strategy surviving this archive still requires the recorded full-book
execution evidence or a new forward execution audit.

