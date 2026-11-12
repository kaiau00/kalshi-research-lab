# Polymarket US retail edge sweep

Read-only. Public GETs only. No orders, no accounts, no Railway, no change to any strategy or pause file. Run on 2026-11-12 from about 16:10Z to 17:15Z. Rules were written in `PREREG.md` before the outcome tables. Two amendments are in that file: the sports window was cut to November before any price was read, and the ITF subgroup was widened to slug tokens `itfme` and `itfwo` before any band PnL was computed.

Fees used below are the published schedule. Taker fee is `Θ × C × p × (1 − p)`, banker's-rounded to the cent on the fill. Primary Θ is 0.095. Primary clip is 25 contracts. Every one of the 12,733 closed sports markets in this pull had `feeCoefficient` 0.095.

## Bottom line

There is no edge here that a few-hundred-dollar account can treat as a daily income. The two leads left open by the prior scan are dead on the numbers that matter.

Buying the 85–97¢ sports favorite, at the displayed ask, with a spread of 3¢ or less, in the hour before the game, lost **0.87¢ per contract** on **1,020** settled markets (25-lot fee). Win rate 91.0% against a mean price of 90.9%. ITF was −0.23¢ on 450 markets. College basketball was −2.0¢ on 121. The new-user coefficient 0.0695 was still −0.67¢. The same-day Pinnacle check, 24 matched moneylines, had **zero** prices in the 85–97¢ band and a mean gap of **−2.2¢** versus power-devigged fair. Every one of the 24 was negative.

The post-election book is still large (555 politics events open past their end date) and it is not a pile of free 99¢ winners. After throwing out books wider than 3¢, 18 quotes remained. The only size was Minnesota's 1st District, bid 95¢ / ask 98¢ for the Democrat, 981 contracts offered. Unofficial results have Jake Johnson (DFL) ahead of Brad Finstad by about 323 votes, and Finstad has asked for a recount. California's 23rd is still uncalled. Louisiana's 5th and 6th are December 12 runoffs, which is why those markets are still open. Gross profit if every tight quote paid is about **$29** on about **$1,663** of cost, and the large piece of that is the recount.

The one pattern that is not already a loss is mechanical and thin. On 1,100 settled BTC and ETH up/down markets, the side displayed at 97–99.5¢ sixty seconds before the window ended won **every time**. Mean price 98.97¢. After the 25-lot fee that is **+0.95¢ per contract**. The live hour did not show a book you can count on: in the last 15 seconds, 60 of 60 polls had no bid or ask, and in the 15–40 second range, 73 of 100 did not either. Size at 99¢ was not recorded. Until a prospective log shows the size, expected dollars per day are not established. The upper bound, if a 25-lot ask at 99¢ were filled on every BTC and ETH 5-minute window and won every time, is about **$0.24 per window**. That upper bound is not a forecast.

## Ranked theses

Dollars per day are for one person, a few hundred dollars, one machine, after the 0.095 taker fee, on what this run actually measured. "Prior" means the November 11 scan, not a new measurement.

| # | Thesis | $/day | What this run found |
|---|---|---|---|
| 1 | Last-minute crypto favorite at 97–99¢, hold to the window end | Not established. Upper bound ~$0.24 per filled 5-minute window if 25 lots exist | 1,100 of 1,100 historical displays won, +0.95¢. Live books usually missing inside 40 seconds. Only paper test worth running |
| 2 | Buy 85–97¢ sports favorites vs settlement | Negative. −0.87¢/contract on 1,020 markets | Killed. Payoff matched the price; the fee took the rest |
| 3 | Same trade on ITF or college basketball | Negative | ITF −0.23¢ (n=450). College basketball −2.0¢ (n=121) |
| 4 | Buy the sports longshot | Negative. −2.3¢/contract, interval entirely below zero | n=1,070. Win rate 6.8% vs an 8.3¢ price |
| 5 | Sports ask vs Pinnacle, same afternoon | Negative on the 24 matches | Mean −2.2¢ vs power fair. No 85–97¢ match in the set |
| 6 | Post-election 97–99¢ carry | About $0 per day | Size that is actually two-sided sits on a recount and an uncalled race |
| 7 | PM US vs Kalshi hourly BTC/ETH strikes, both taker | One flicker this afternoon | 549 quoted pairs, 1 tight pair above 1¢, once, 3.2¢, Kalshi size 189 |
| 8 | Trade the BRTI 60-second average inside the last minute | Not shown | Settlement equals the public 1-second close at T−1 on 96/96 markets. No fillable partial-average lock |
| 9 | Maker-quote NFL/NBA/college and keep the spread | About $0 after adverse selection | Median spread 0.5¢ NFL, 1¢ NBA, college basketball, ATP, NHL, UFC. Prior fill sim was not repeated |
| 10 | New-user Θ=0.0695 for 7 days | $0 by itself | Sports favorite band still −0.67¢ |
| 11 | Coin-flip sports taker (50–70¢) | Negative. −3.4¢/contract | n=4,782. Interval entirely below zero. That is the fee plus a small rich bias |
| 12 | CPI / jobs / Fed, trade the print | $0 on a normal day | November CPI is December 11. November jobs are December 5. Books are wide a month out. No same-day print was sniped |
| 13 | Weather decided-bracket scalp | $0 | Prior Study 033-W failed its gates. Not rerun. 30 open weather events, none past end date |
| 14 | Two-sided arb, or buy every name in a winner set | $0 | Prior scan: no size after fees; 0 of 2,097 mutually exclusive observations were net positive. Not rerun |
| 15 | Culture / mentions settlement lag | $0 | 226 open culture events, 1 past its end date |
| 16 | Early-window crypto favorite, Bosona-style | Not measured | This run tested the last minute, not the first two minutes. Prior international edge was about the size of this venue's fee |
| 17 | Live sports vs a faster score feed | Not measured | Open-game spreads are about 1¢. Prior in-play probe pointed at adverse selection |
| 18 | Gold and silver Chainlink windows | Not measured | Not pulled |

## What was tested

### Sports favorites, against settlement

Universe: closed full-game, match, and fight winners with `gameStartTime` in `[2026-11-01T00:00:00Z, 2026-11-12T12:00:00Z)`. October was dropped in Amendment A before any price was read, because a single October day was more than 14,000 closed contracts. Decision price: last minute of price history in the three hours before start, and only if that print is 10 to 45 minutes before the open. Buy the higher display. Primary rows also need `longPrice + shortPrice − 1 ≤ 0.03`. Settlement: the listed side price when it was 0, 1, or 0.5, otherwise the settlement endpoint. Eight listed 0/1 prices were checked against the endpoint and all eight matched. Of 12,733 markets, 271 settled at 0.5 and 103 settled at some other fraction. Those payoffs were kept.

| Band | n | Win rate | Mean price | Mean payoff | PnL / contract | 95% interval |
|---|---:|---:|---:|---:|---:|---|
| 0.50–0.70 | 4,782 | 58.9% | 0.592 | 0.581 | −3.37¢ | −4.75¢ to −2.00¢ |
| 0.70–0.85 | 1,967 | 77.4% | 0.762 | 0.770 | −0.98¢ | −2.81¢ to +0.86¢ |
| 0.85–0.90 | 378 | 87.3% | 0.871 | 0.870 | −1.09¢ | −4.45¢ to +2.27¢ |
| 0.90–0.95 | 439 | 92.0% | 0.920 | 0.918 | −0.91¢ | −3.45¢ to +1.64¢ |
| 0.95–0.97 | 203 | 95.6% | 0.955 | 0.956 | −0.36¢ | −3.20¢ to +2.48¢ |
| **0.85–0.97** | **1,020** | **91.0%** | **0.909** | **0.908** | **−0.87¢** | **−2.62¢ to +0.88¢** |
| 0.97–0.995 | 501 | 98.0% | 0.985 | 0.980 | −0.63¢ | −1.86¢ to +0.59¢ |

The pre-registered kill rule was: n ≥ 200 and mean PnL ≤ 0. Both are true. The interval still touches zero, so this is a kill of a claimed 1–2¢ edge, not a precise estimate of a 0.9¢ loss. A 25-lot clip on all 1,020 would have lost about $221.

ITF men (`itfme`) −0.13¢ (n=239). ITF women (`itfwo`) −0.34¢ (n=211). Together −0.23¢ (n=450). College basketball (`cbb`) −2.03¢ (n=121). The rule that would have kept a subgroup alive required n ≥ 80 and a positive mean. Neither subgroup has a positive mean.

A few league tokens were positive and were not pre-specified: women's college basketball +0.68¢ (n=101), ATP +0.34¢ (n=34), college football +5.7¢ (n=23), WTA +2.5¢ (n=19). Those are descriptive. They are not a new lead.

The cheap side, same spread gate, price 3–15¢: n=1,070, win rate 6.8% against a mean price of 8.3¢, PnL −2.27¢, interval entirely below zero.

One contract is worse than 25 at these prices, because a 1-lot fee at 91¢ rounds up to a full cent (0.095 × 0.91 × 0.09 = 0.78¢, which rounds to 1¢). The 1-lot column on the lead band is −0.90¢.

### Pinnacle, same afternoon

Guest moneylines, pre-game, tennis and basketball, matched on last names to open Polymarket US winners. Two bad joins were thrown out and the script was rerun: the first joined futures specials, the second treated the league-list side prices as the two outcome prices. Those list prices are the yes bid and the yes ask written onto the two sides. The rerun buys the long side at the yes ask and the short side at one minus the yes bid.

128 Polymarket games, 109 Pinnacle moneylines, 35 name matches, 24 priced. Mean net versus power-devigged fair: **−2.22¢**. Versus proportional fair the sign is the same. **0 of 24 were positive.** None had an ask in 85–97¢. The dearest were 80¢: Pistons 80¢ versus a power fair of 80¢ (net −1.4¢), 76ers 75¢ versus 76¢. This is one afternoon and 24 games. It agrees with the prior scan's "buying the ask is about −2.6¢."

### Politics past the end date

555 events, 4,117 markets, still open with `endDate` before 2026-11-12T16:05Z. A raw ask in 97–99.5¢ showed up 3,946 times. 3,928 of those were books wider than 3¢, usually a 1¢ bid and a 99¢ ask, which is an empty book rather than a market sitting at 99¢. The 3¢ gate was applied after seeing that, and it is labeled as a clarification in `results/politics_tight.json`.

18 tight quotes. Total size 1,692 contracts, cost about $1,663, gross receipt if every one paid about $29 before fees. Almost all of the size is three contracts:

- MN-01 Democrat: bid 95¢, ask 98¢, 981 contracts on the ask. Minnesota's unofficial file has Jake Johnson (DFL) 163,055 and Brad Finstad (R) 162,733. Finstad asked for a recount. The canvassing board meets November 19. This is a 98¢ price on a 0.1% margin, not a delayed settlement.
- CA-23 Democrat: bid 1¢ (size 452), ask 2¢. The Republican bid is 98¢ and there is no ask, so the leader cannot be bought. Jay Obernolte (R) led Tessa Hodge (D) 106,793 to 102,964 with about 95% counted on the morning of November 12. Not called.
- LA-05 and LA-06 are December 12 runoffs. Prices are 71–99¢ and 91–98¢, not a pinned 99¢. The November 3 end date is the jungle primary. The race is not over.

Sources are in `results/politics_verification.json`.

### Crypto up/down, one minute before the end

BTC and ETH, 5-minute and 15-minute, `windowEnd` in `[2026-11-11T00:00:00Z, 2026-11-12T11:00:00Z)`. 1,120 markets, 1,113 with a quote in the 60–90 seconds before the end and a spread of 4¢ or less. The spread on 1,078 of the 1,100 high quotes was exactly zero: the two displays summed to 1.00.

| Band | n | Wins | Mean price | PnL / contract |
|---|---:|---:|---:|---:|
| 0.85–0.97 | 12 | 12 | 0.938 | +5.7¢ |
| 0.97–0.995 | 1,100 | 1,100 | 0.990 | +0.95¢ |

The 85–97¢ cell is under the pre-registered bar of 300. Twelve wins is what a 94¢ price looks like in a small sample; it is not a separate strategy. The 99¢ cell is the whole book. A fair 99% coin does not win 1,100 times in a row. The contract was already decided, and the display had not moved from 99¢ to $1. The 25-lot fee at 99¢ is a fraction of a cent (0.095 × 25 × 0.99 × 0.01 = 2.35¢ on the fill, about 0.09¢ per contract).

That is a display result. The history endpoint does not include size.

### Live books, 16:15Z–16:47Z

768 polls, 20 windows, all settled. The pre-registered entry was the last sample with 20–40 seconds left, ask 80–98¢, spread ≤ 4¢, index at least 2 bps through the reference price.

Two windows produced that entry. Both were buys at 98¢, both won, both +1.8¢ per contract. Most 20–40 second slots had no bid or ask in the response (73 of 100 polls in the wider 15–40 second range). All 60 polls inside the last 15 seconds had no bid or ask. When a quote did exist in the last 40 seconds, the median spread was 2¢, and 11 of 27 quotes were already at 97¢ or higher, or at 3¢ or lower.

The 60–90 second sensitivity included a buy of the BTC up side at 89¢ that lost the contract (−90¢ per contract). Pooling that with the 98¢ winners is how the script's combined mean landed at −9¢ on 7 trades. The primary bucket was the two 98¢ winners. n=2.

Across the live windows, each window's `priceToBeat` equaled the previous window's `settlementPrice` on the same horizon. That matches the identity check below.

### The 60-second average

On 96 settled up/down markets (BTC, ETH, SOL, XRP × 5m, 15m, 1h, eight each), the published `settlementPrice` and the published `priceToBeat` both equaled the public 1-second close at the boundary minus one second, exactly, 96 of 96. The mean of the 60 closes in the preceding minute matched none of them. Every candle in the checks carried `tickCount` 60.

Kalshi's own rule text, pulled with the hourly markets, says the contract uses "the simple average of the sixty seconds of CF Benchmarks' BRTI" (and ERTI for ether) before the hour. Polymarket's FAQ says the same thing. The public series currently behaves as if each 1-second close is already that statistic: settlement is the close at T−1, and averaging those closes a second time is the wrong reproduction. A raw BRTI print was not available from CF Benchmarks (the two public URLs tried returned 404 and 400), so this does not separate "the close is the average" from "the close is a single print and the FAQ is stale." Either way, there was no second-by-second residual a retail script could trade inside the minute. The book, when it was visible, was already at 98–99¢ or was absent.

### Kalshi hourly strikes

`KXBTCD` / `KXETHD` versus Polymarket hourly above/below, strikes within 3% of the index, 26 passes over 20 minutes, 549 quoted observations. Net uses the unrounded per-contract fees. 19 observations were positive. One of them had both books 2¢ wide or tighter and a net above 1¢: BTC above $71,600, Polymarket 60/61¢, Kalshi 68/69¢, net about 3.2¢ buying Polymarket and selling Kalshi, Kalshi bid size 189, one pass, not repeated. The other positives were wider Polymarket books or sub-cent. This afternoon did not show a standing arb. It is the same short-lived gap the prior 20-second study saw 4 times in 120 snapshots.

### Inventory that was not a PnL test

Open events, from an offset search: politics 686 (553 past end date), sports 3,977 (13 past end), crypto 64, culture 226 (1 past end), weather 30 (0 past end), economics 79 (2 past end). Climate, finance, mentions, and world returned no events under those tag slugs.

Median winner-market spread on the open league pages: NFL 0.5¢ (29 quotes), NBA, college basketball (`cbb`), ATP, NHL, and UFC about 1¢. The league slug `itf` returned no open events. ITF in the settled history is `itfme` and `itfwo`.

The economics tag is mostly year-end and month-ahead ladders. November CPI and core CPI settle December 11. November unemployment and payrolls settle December 5. The December Fed decision settles December 10. A month before the CPI print, "above 3.6% YoY" was 73/90¢ and "above 3.5%" was 97/98¢. That is a wide book, not a release you can outrun. October CPI was in the active list with an end date of November 11; its book was not pulled. Treasury yield ladders for November 13 had no two-sided quotes on the strikes that came back first. The search endpoint ignored the query string and returned the same basketball games for "CPI" and "jobs report," so it was not used.

## Pre-registered paper test

Only one measurement is not already negative, and it is a display without a size. The test below is new. It is not a claim that the 1,100 historical wins were fills.

**Name.** Crypto last-minute size test. Paper only. No orders.

**Universe.** BTC and ETH 5-minute up/down on Polymarket US. Windows that end during the recording.

**Entry, frozen.** The first poll in a window where all of these hold: 20 to 70 seconds left, the favorite ask is in `[0.97, 0.99]`, the spread is 2¢ or less, and the ask size is at least 25 contracts. Buy 25 at that ask in the log. One entry per window. If the ask is 99¢ the pre-registered live rule from this run would have skipped it; this test includes 99¢ because that is where the historical mass was.

**Fee.** Θ = 0.095, 25-contract fill, banker's cent. Hold to `settlementPrice`. Up wins on a tie with `priceToBeat`.

**Pass.** At least 200 filled windows. Mean PnL per contract positive on the first 100 and on the second 100, and still positive on the second 100 after dropping its three best windows. If 7 days produce fewer than 30 fills, stop. There is no size, and the 0.95¢ display is not a trade.

**Do not do.** Do not lower the size floor after seeing the log. Do not add 15-minute or hourly windows. Do not trade the 80–96¢ band from this sample. Do not paper-trade sports favorites, politics recounts, or Kalshi crosses off this run.

## What was not redone

The prior cross-venue scan's two-sided arbs, the 2,097 mutually exclusive sets, and Study 033-W's weather gates. Maker fills were not resimulated. A score feed was not compared to in-play props.

## Files

`PREREG.md` is the rule sheet. Scripts are in `scripts/`. Result tables are in `results/`. `sports_raw.jsonl` is the settled sports pull (12,733 rows). The market-list duplicate and the derived trades file were not kept; `analyze_sports.py` rebuilds the table from the raw file.
