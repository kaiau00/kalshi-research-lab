"""Fixed-time, indicative taker-price calibration screen for Study 032."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, ROUND_UP

FEE_RATE = Decimal("0.07")
HORIZONS_SECONDS = (300, 900, 1800)
BANDS = tuple(Decimal(value) for value in ("0.00", "0.20", "0.40", "0.60", "0.80", "1.00"))


@dataclass(frozen=True)
class IndicativeQuote:
    event_date: str
    ticker: str
    horizon_seconds: int
    side: str
    ask: Decimal
    outcome: bool


def taker_fee(price: Decimal) -> Decimal:
    return (FEE_RATE * price * (Decimal("1") - price)).quantize(Decimal("0.000001"), rounding=ROUND_UP)


def adverse_price(price: Decimal) -> Decimal | None:
    stressed = price + Decimal("0.01")
    return stressed if stressed < Decimal("1") else None


def quotes_at_fixed_horizons(markets: dict[str, dict], candle_rows: dict[str, list[dict]]) -> list[IndicativeQuote]:
    """Build causal quotes using only the last one-minute candle at/before each fixed horizon."""
    output: list[IndicativeQuote] = []
    for ticker, rows in candle_rows.items():
        market = markets.get(ticker)
        if not market or market.get("result") not in {"yes", "no"}:
            continue
        close = int(market["close_second"])
        event_date = market["event_date"]
        ordered = sorted(rows, key=lambda row: int(row["end_period_ts"]))
        for horizon in HORIZONS_SECONDS:
            decision = close - horizon
            eligible = [row for row in ordered if int(row["end_period_ts"]) <= decision]
            if not eligible or decision - int(eligible[-1]["end_period_ts"]) > 60:
                continue
            quote = eligible[-1]
            try:
                yes_ask = Decimal(str(quote["yes_ask"]["close"]))
                yes_bid = Decimal(str(quote["yes_bid"]["close"]))
            except (KeyError, TypeError, ValueError, ArithmeticError):
                continue
            if not Decimal("0") < yes_ask < Decimal("1") or not Decimal("0") < yes_bid < Decimal("1"):
                continue
            outcome_yes = market["result"] == "yes"
            output.extend(
                [
                    IndicativeQuote(event_date, ticker, horizon, "yes", yes_ask, outcome_yes),
                    IndicativeQuote(event_date, ticker, horizon, "no", Decimal("1") - yes_bid, not outcome_yes),
                ]
            )
    return output


def _band(price: Decimal) -> str:
    for lower, upper in zip(BANDS, BANDS[1:], strict=True):
        if lower <= price < upper or (upper == Decimal("1") and price == upper):
            return f"{lower:.2f}-{upper:.2f}"
    raise ValueError("Price outside binary range")


def _summary(quotes: list[IndicativeQuote]) -> dict:
    groups: dict[tuple[int, str, str], list[IndicativeQuote]] = defaultdict(list)
    for quote in quotes:
        groups[(quote.horizon_seconds, quote.side, _band(quote.ask))].append(quote)
    rows = []
    for (horizon, side, band), group in sorted(groups.items()):
        stressed = [(quote, adverse_price(quote.ask)) for quote in group]
        executable = [(quote, price) for quote, price in stressed if price is not None]
        net = sum(
            ((Decimal("1") if quote.outcome else Decimal("0")) - quote.ask - taker_fee(quote.ask) for quote in group),
            Decimal("0"),
        )
        stressed_net = sum(
            (
                (Decimal("1") if quote.outcome else Decimal("0")) - price - taker_fee(price)
                for quote, price in executable
            ),
            Decimal("0"),
        )
        rows.append(
            {
                "seconds_before_close": horizon,
                "side": side,
                "ask_band": band,
                "quotes": len(group),
                "observed_win_rate": str(
                    (Decimal(sum(quote.outcome for quote in group)) / Decimal(len(group))).quantize(Decimal("0.0001"))
                ),
                "mean_ask": str((sum(quote.ask for quote in group) / len(group)).quantize(Decimal("0.0001"))),
                "indicative_taker_net_pnl": str(net.quantize(Decimal("0.0001"))),
                "one_cent_stressed_quotes": len(executable),
                "one_cent_stressed_net_pnl": str(stressed_net.quantize(Decimal("0.0001"))),
            }
        )
    return {"quotes": len(quotes), "bands": rows}


def calibration_report(quotes: list[IndicativeQuote]) -> dict:
    """Split by whole event dates; this is a screen, not an executable backtest."""
    dates = sorted({quote.event_date for quote in quotes})
    cutoff = dates[(len(dates) * 3) // 5 - 1] if dates else None
    development = [quote for quote in quotes if cutoff and quote.event_date <= cutoff]
    validation = [quote for quote in quotes if cutoff and quote.event_date > cutoff]
    return {
        "registration": {
            "study": "032",
            "kind": "exploratory fixed-time displayed-quote calibration screen",
            "horizons_seconds": list(HORIZONS_SECONDS),
            "fee": "ceil_6dp(0.07 * price * (1-price)) per one-contract indicative taker fill",
            "stress": "one-cent worse displayed ask; observations at 1.00 cannot pass stress",
            "limitations": [
                "No order-book depth, queue position, or actual fill is inferred from a candle.",
                "All contracts in an event are correlated; quote rows are not independent trades.",
                "This screen selects no strategy and does not authorize Demo or live execution.",
            ],
        },
        "date_split": {"development_through": cutoff, "development_dates": len({q.event_date for q in development}), "validation_dates": len({q.event_date for q in validation})},
        "development": _summary(development),
        "validation": _summary(validation),
    }
