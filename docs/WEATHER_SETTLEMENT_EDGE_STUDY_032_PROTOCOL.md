# Weather Settlement Edge Study 032

## Question

Can a small, read-only research system identify an executable edge in Kalshi
daily-high-temperature markets from the exact contract settlement source,
observed intraday weather state and market prices?

This is a feasibility study. It does not authorize Demo or production orders,
does not alter BTC research, and does not assume that a maker order fills at a
historical quote.

## First market family

The first inventory target is `KXHIGHNY` (New York City daily maximum
temperature). On October 27, 2026, active and finalized market rules retrieved
from Kalshi named **The Weather Company** as the settlement source for this
family. The series therefore cannot be labelled with NWS Daily Climate Reports
or METAR data unless the individual contract rules explicitly name those
sources.

Every later market family is admitted only after its actual `rules_primary`,
station identifier, local-time convention and outcome type are recorded. The
market rule controls over a general help article.

## Candidate hypotheses

1. **Late-day lock-in.** After the observed maximum has passed and a defined
   cooling/observation condition holds, outcomes above the observed maximum may
   be materially over-priced.
2. **Forecast calibration.** A specified official-source forecast may have a
   stable, station-specific error distribution that the order book has not
   fully incorporated.

Neither hypothesis assumes an advertised forecast bias, a claimed win rate or
an NWS/TWC equivalence. They are tested separately.

## Required evidence

For each selected event date, retain Kalshi market metadata, rules, result,
expiration value and price history; the source named in the contract rules;
station/time-zone mapping; and a reconstruction showing the recorded source
agrees with Kalshi's final expiration value. If the official source cannot be
obtained historically at the required timestamp, the affected rule is
prospective-only. It must not be backtested using a convenient substitute.

## Execution assumptions

Historical candles may screen directional value, but they do not contain
order-book depth, queue position, or an order's actual fill. Any historical
maker result is labelled non-executable until a prospective book recorder and
Demo audit measure those mechanics. Taker simulations include applicable fees
and adverse-price stress.

## Staged gates

1. **Inventory:** at least 90 finalized event dates, valid contract rules and
   a verified settlement-source mapping.
2. **Data:** at least 80% of retained dates have time-aligned source and
   market-price observations; missingness is disclosed by station/date.
3. **Development:** a locked rule is positive after fees, one-cent stress and
   removal of its three largest winners.
4. **Validation:** the same rule passes later untouched dates with positive
   performance in at least four of five chronological blocks.
5. **Operational:** a prospective recorder and Demo audit reproduce the data
   and order assumptions before any pilot discussion.

## Exclusions

- No orders, Demo or live;
- no NWS/METAR proxy for a Weather Company-settled contract;
- no inferred fill from a candle;
- no Jev in the first study; and
- no parameter search on validation data.
