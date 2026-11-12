# Pre-registered tests (frozen before outcome tables)

Frozen at 2026-11-12T16:10:00Z, before the collectors below were allowed to write result tables.
This file is the rule sheet. A bugfix that changes a rule is a new test and must be labeled as such.
Schema probes before this timestamp are not results. One sports price path was inspected while checking
that minute history exists (`aec-nfl-lv-sf-2026-11-08`) and is excluded. Crypto markets whose books or
paths were inspected (the SOL 11:00Z hour, the BTC 14:00Z hour, the BTC 15:40Z and 15:50Z 5-minute
windows, and the 16:00Z 5-minute books) sit outside the crypto and live windows below.

Public GETs only. No accounts, no orders.

## Fees used in every dollar figure

Polymarket US taker fee is `Θ × C × p × (1 − p)`, banker's rounding (half to even) to the cent, per fill.
Primary Θ is 0.095. The new-account coefficient 0.0695 is a secondary column, not the kill rule.
Primary clip is 25 contracts (about $21–$24 when p is 0.85–0.97). A 1-contract column is reported
because a 1-lot fee often rounds to zero and would flatter favorites. Kalshi comparison fee is the
user-stated `0.07 × C × p × (1 − p)` unrounded, with a cent-ceiling variant shown beside it.

## T1. Sports favorite settlement

Question: after the taker fee, does buying the displayed favorite in the 85–97¢ band before a game
make money? This tests the price against the later settlement. It does not re-test the Pinnacle gap.

- Universe: `GET /v1/markets`, `closed=true`, `categories=sports`, `endDate` from 2026-10-15T00:00:00Z
  through 2026-11-13T00:00:00Z, then keep `gameStartTime` in `[2026-10-15T00:00:00Z, 2026-11-12T12:00:00Z)`.
- Types kept: `sportsMarketType` equal to `moneyline`, or ending in `full_game_winner`, `match_winner`,
  or `fight_winner`. Futures, props, totals, spreads, and period or map winners are out.
- Excluded slug: `aec-nfl-lv-sf-2026-11-08`.
- Decision price: last `GET /v1/price-history` point with `fidelity=1` inside
  `[gameStart−3h, gameStart−10min]`. `longPrice` is the Yes display (ask-like). `shortPrice` is the
  No display (ask-like). Primary rows need that point's timestamp within 45 minutes before start
  (so it is not an hours-old print) and at or before start−10min.
- Spread proxy: `longPrice + shortPrice − 1`. Primary rows need spread ≤ 0.03, both prices in `(0, 1)`,
  and a unique higher price.
- Bands on the higher display: `[0.50, 0.70)`, `[0.70, 0.85)`, `[0.85, 0.90)`, `[0.90, 0.95)`,
  `[0.95, 0.97)`, `[0.97, 0.995]`. The lead band is the pool `[0.85, 0.97)`.
- Settlement: `GET /v1/markets/{slug}/settlement`. Long payoff is the settlement value. Short payoff
  is `1 − settlement`. Values outside `[0, 1]`, or a failed lookup, are exclusions, not wins.
- Primary PnL: 25-contract fill, Θ = 0.095, per-contract net = payoff − price − fee/25.
- Kill rule: if the lead band has n ≥ 200 and mean per-contract PnL ≤ 0, the general "buy 85–97¢
  sports favorites" lead is dead for this population. If n < 200, the test is inconclusive, not a pass.
- Pre-specified subgroups, and the only ones that can stay open if the pool dies: league token `itf`
  (or the question contains "ITF"), and college basketball tokens `cbb`, `ncaab`, `ncaam`. A subgroup
  stays a candidate only if n ≥ 80 and mean PnL > 0. Otherwise it is unresolved or dead with the pool.
  Other league tokens are descriptive. No token is promoted because it won.
- Also report the cheap side in `[0.03, 0.15)` on the same primary spread gate, as a control.

## T2. Post-election quotes at 97–99¢

Question: are open politics markets past `endDate` and quoted at 97–99¢ settled-in-all-but-name
winners you can still buy, or are the quotes wrong, empty, or not yet knowable?

- Universe: `GET /v1/events?tagSlug=politics&active=true&closed=false&endDateMax=2026-11-12T16:05:00Z`,
  paged until empty.
- A carry candidate has an executable ask on one side inside `[0.97, 0.995]`. Yes ask is the market
  ask. No ask is `1 − yes bid` only when the yes bid exists. Side "price" without a bid or ask is
  recorded as non-executable and is not a candidate.
- Book size is the top-of-book quantity at that ask, from `GET /v1/markets/{slug}/book` when the
  screen hits. Missing size stays missing. It is not filled in.
- Verification sample, fixed before reading outcomes: every candidate whose question is a governor
  or senate winner; if more than 40 candidates remain, add the 20 highest asks not already included
  and 10 more drawn with seed `20261112`. If 40 or fewer, verify all. Sources are public election
  results (Associated Press, state sites, Ballotpedia, Wikipedia citing those). Polymarket prices
  are not an outcome. Disagreement or no certified result is "unresolved", not a win.
- A confirmed winner is worth `1 − ask` minus the fee, on the displayed size only, capital locked
  until Polymarket resolves it. A confirmed loser kills that quote. Unresolved is not edge.

## T3. Crypto up/down favorites in the last minute, and the BRTI average

Question: at 60 seconds before the window ends, does buying the displayed favorite still pay after
fees, and does the public 1-second series match the documented 60-second average?

- Calibration universe: closed `ASSET_PRICE_MARKET_TYPE_UP_DOWN`, BTC and ETH, horizons `5m` and
  `15m`, `windowEnd` in `[2026-11-11T00:00:00Z, 2026-11-12T11:00:00Z)`.
- Decision point: latest price-history sample with timestamp in `[windowEnd−90s, windowEnd−60s]`.
  No point in that window means the market is excluded.
- Up wins when `settlementPrice >= priceToBeat` (ties count as Up, per the crypto FAQ). Null terms
  exclude the market.
- Same spread gate (≤ 0.04 here, because near-expiry books gap) and the same bands and 25-lot fee
  as T1. Lead band `[0.85, 0.97)`. The `[0.97, 0.995]` band is reported separately because a 99¢
  quote with one minute left is a different trade. Cheap side `[0.02, 0.15)` is the control.
- Kill rule: n ≥ 300 and mean PnL ≤ 0 in the lead band kills "buy the crypto favorite one minute
  before the end" for this window. One 35-hour window is one volatility regime. It can kill a large
  edge. It cannot prove a 1¢ edge.
- Identity check, separate and descriptive: for the 8 most recent settled up/down markets in each
  of BTC/ETH/SOL/XRP × 5m/15m/1h before 2026-11-12T16:10:00Z, compare `settlementPrice` and
  `priceToBeat` to (a) the 1-second close at the boundary minus 1 second and (b) the mean of the
  1-second closes on `[boundary−60s, boundary)`. Report exact-to-the-cent match counts. This sample
  may include markets looked at during schema checks. It is about the index definition, not PnL.

## T4. Live last-minute books (pilot)

Question: in the last half-minute, is the ask still cheap relative to an index that has already
moved through the reference price?

- Record BTC and ETH 5m and 15m books about every 5 seconds, plus the public 1-second index.
- Analyzed windows are those with `windowEnd >= 2026-11-12T16:15:00Z` that finish during the
  recording. Earlier windows are log-only.
- Pre-specified entry: the last sample with seconds-left in `[20, 40]`, one side's ask in
  `[0.80, 0.98]`, spread ≤ 0.04, and the index at least 2 bps through `priceToBeat` on that side.
  Hypothetical 25-lot buy at that ask. Sensitivities, also pre-specified: seconds-left in `[60, 90]`
  and in `[5, 15]`, same price and distance gates.
- Settlement is the market's later `settlementPrice`. n will be small. This pilot cannot confirm
  an edge. It can show the ask is already 99¢, or that the books are too wide to use.

## T5. Same-day cross-sections (not kill tests)

These describe the book today. They do not confirm T1–T4.

- Pinnacle guest moneylines, pre-game only, tennis and basketball, proportional and power de-vig,
  matched to open Polymarket US full-game winners on normalized names. Net is fair minus Polymarket
  ask minus the 25-lot fee. Reported only for matched pairs. Unmatched lines are counted and dropped.
- Kalshi `KXBTCD` / `KXETHD` versus Polymarket US hourly above/below at the same hour. Match Polymarket
  strike `S` to Kalshi `greater` with floor `S − 0.01`. Skip a pair when the index is within $1 of
  the strike (the 1¢ contract wording can differ). Net arb per contract uses both asks and both bids
  and both fees. One snapshot, plus 30-second repeats for 20 minutes. Positive nets are listed with
  sizes. This does not replace the prior 120-snapshot lag study.

## Amendment A (2026-11-12T16:12Z)

Written before any T1 price, settlement, or PnL was computed. One October day of closed
sports markets was more than 14,000 contracts, almost all props, and the list had not
been saved. T1's `gameStartTime` window is narrowed to `[2026-11-01T00:00:00Z, 2026-11-12T12:00:00Z)`.
The bands, spread gate, fee, clip, subgroups, and kill rule are unchanged. No October
price was read.

## Amendment B (2026-11-12T16:50Z)

The ITF subgroup was defined as league token `itf`. The listed slugs use `itfwo` and `itfme`.
Before any favorite-band PnL was computed, the subgroup is any league token that starts with `itf`,
plus a question containing "ITF". College basketball is unchanged (`cbb`, `ncaab`, `ncaam`).

## What this file does not reopen

Mutually exclusive sets, two-sided taker arbs, and the weather METAR lock-in were already measured
and failed. They are not re-run. Maker quoting is ranked from the prior probe plus a fresh spread
inventory, not from a new fill simulator.
