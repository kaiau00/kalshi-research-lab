"""Same-day Pinnacle moneylines versus open Polymarket US winners.

The guest key is read from PINNACLE_GUEST_KEY and is never written to disk.
Rules: PREREG.md T5. Descriptive only.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from decimal import Decimal
from pathlib import Path

from common import PM, PRIMARY_CLIP, THETA_RETAIL, RateLimiter, dec, get_json, taker_fee

ROOT = Path(__file__).resolve().parents[1]
PINNACLE = "https://guest.api.arcadia.pinnacle.com/0.1"
KEEP_LEAGUE = re.compile(r"ITF|Challenger|ATP|WTA|NCAA|College|NBA|Euroleague|EuroCup|Basketball", re.IGNORECASE)


def pinnacle_get(path: str, key: str, limiter: RateLimiter) -> object:
    delay = 1.0
    last_error: Exception | None = None
    for _ in range(4):
        limiter.wait()
        request = urllib.request.Request(
            PINNACLE + path,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.pinnacle.com/",
                "X-API-Key": key,
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                return json.load(response)
        except Exception as error:  # noqa: BLE001 — retry 403s from the guest API
            last_error = error
            import time

            time.sleep(delay)
            delay = min(delay * 2, 12)
    assert last_error is not None
    raise last_error


def american_to_implied(price: int | float) -> Decimal:
    value = Decimal(str(price))
    if value > 0:
        decimal_odds = Decimal(1) + value / Decimal(100)
    else:
        decimal_odds = Decimal(1) + Decimal(100) / abs(value)
    return Decimal(1) / decimal_odds


def proportional(implied: list[Decimal]) -> list[Decimal]:
    total = sum(implied, Decimal(0))
    return [item / total for item in implied]


def power(implied: list[Decimal]) -> list[Decimal]:
    low, high = Decimal("0.2"), Decimal("3")
    for _ in range(40):
        mid = (low + high) / 2
        total = sum(item**mid for item in implied)
        if total > 1:
            low = mid
        else:
            high = mid
    exponent = (low + high) / 2
    return [item**exponent for item in implied]


def normalize(name: str) -> str:
    tokens = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    stop = {"fc", "the", "vs", "at", "club"}
    return " ".join(token for token in tokens if token not in stop)


def last_name(name: str) -> str:
    parts = normalize(name).split()
    return parts[-1] if parts else ""


def pm_games(limiter: RateLimiter) -> list[dict]:
    games = []
    for league in ("atp", "wta", "itf", "nba", "ncaab", "cbb", "ncaam", "euroleague"):
        try:
            payload = get_json(f"{PM}/v2/leagues/{league}/events?limit=40&type=sport", limiter)
        except Exception as error:  # noqa: BLE001
            games.append({"league": league, "error": f"{type(error).__name__}: {error}"})
            continue
        for event in payload.get("events") or []:
            participants = []
            for team in event.get("teams") or event.get("participants") or []:
                if isinstance(team, dict):
                    participants.append(team.get("name") or team.get("safeName") or "")
            title = event.get("title") or ""
            if len(participants) < 2 and " vs. " in title:
                participants = [part.strip() for part in title.split(" vs. ")]
            elif len(participants) < 2 and " vs " in title:
                participants = [part.strip() for part in title.split(" vs ")]
            market = None
            for item in event.get("markets") or []:
                kind = item.get("sportsMarketType") or ""
                if kind.endswith("full_game_winner") or kind.endswith("match_winner") or kind == "moneyline":
                    market = item
                    break
            if market is None or len(participants) < 2:
                continue
            long_side = next((side for side in market.get("marketSides") or [] if side.get("long")), {})
            short_side = next((side for side in market.get("marketSides") or [] if not side.get("long")), {})
            # The league-events payload puts the yes bid on one side and the yes ask on the
            # other. Those are not the two outcome prices. Buy-long is the yes ask. Buy-short
            # is one minus the yes bid.
            bid = dec((market.get("bestBidQuote") or {}).get("value") if isinstance(market.get("bestBidQuote"), dict) else None)
            ask = dec((market.get("bestAskQuote") or {}).get("value") if isinstance(market.get("bestAskQuote"), dict) else None)
            games.append(
                {
                    "league": league,
                    "title": title,
                    "start": event.get("startTime") or event.get("startDate"),
                    "slug": market.get("slug"),
                    "participants": participants[:2],
                    "long_label": long_side.get("description"),
                    "short_label": short_side.get("description"),
                    "long_price": None if ask is None else str(ask),
                    "short_price": None if bid is None else str(Decimal(1) - bid),
                    "bestBid": None if bid is None else str(bid),
                    "bestAsk": None if ask is None else str(ask),
                }
            )
    return games


def pinnacle_lines(key: str, limiter: RateLimiter) -> list[dict]:
    lines = []
    for sport, label in ((33, "tennis"), (4, "basketball")):
        leagues = pinnacle_get(f"/sports/{sport}/leagues?all=false", key, limiter)
        chosen = [league for league in leagues if KEEP_LEAGUE.search(league.get("name") or "")]
        print(f"pinnacle {label} leagues {len(leagues)} kept {len(chosen)}", flush=True)
        for league in chosen[:25]:
            league_id = league["id"]
            try:
                matchups = pinnacle_get(f"/leagues/{league_id}/matchups", key, limiter)
                markets = pinnacle_get(f"/leagues/{league_id}/markets/straight", key, limiter)
            except Exception as error:  # noqa: BLE001
                print("league error", league.get("name"), error, flush=True)
                continue
            by_id = {}
            for market in markets:
                if market.get("type") == "moneyline" and market.get("period") == 0:
                    by_id.setdefault(market.get("matchupId"), market)
            for matchup in matchups:
                if matchup.get("type") != "matchup" or matchup.get("parentId") or matchup.get("isLive"):
                    continue
                parts = matchup.get("participants") or []
                if len(parts) != 2:
                    continue
                market = by_id.get(matchup.get("id"))
                if not market:
                    continue
                named_prices = []
                by_alignment = {part.get("alignment"): part.get("name") for part in parts}
                for price in market.get("prices") or []:
                    if "price" not in price or len(market.get("prices") or []) != 2:
                        continue
                    name = by_alignment.get(price.get("designation"))
                    if not name:
                        name = next((part.get("name") for part in parts if part.get("id") == price.get("participantId")), None)
                    if name:
                        named_prices.append({"name": name, "price": price.get("price")})
                if len(named_prices) != 2:
                    continue
                lines.append(
                    {
                        "sport": label,
                        "league": league.get("name"),
                        "participants": [part.get("name") for part in parts],
                        "start": matchup.get("startTime"),
                        "prices": named_prices,
                    }
                )
    return lines


def match_games(pm_rows: list[dict], lines: list[dict]) -> list[dict]:
    matched = []
    for game in pm_rows:
        if game.get("error"):
            continue
        names = [last_name(name) for name in game["participants"]]
        if any(len(name) < 3 for name in names):
            continue
        for line in lines:
            blob = " ".join(normalize(name) for name in line["participants"])
            if all(name in blob.split() or name in blob for name in names):
                # Require both last names as whole tokens when possible.
                tokens = set(blob.split())
                if not all(name in tokens for name in names):
                    continue
                matched.append({"pm": game, "line": line})
                break
    return matched


def side_fair(game: dict, line: dict) -> dict | None:
    named = [(price["name"], american_to_implied(price["price"])) for price in line["prices"]]
    if len(named) != 2:
        return None
    prop = proportional([item[1] for item in named])
    pow_ = power([item[1] for item in named])
    # Buy the displayed favorite: the Polymarket side with the higher ask-like price.
    candidates = []
    for label, raw_price in ((game.get("long_label"), game.get("long_price")), (game.get("short_label"), game.get("short_price"))):
        price = dec(raw_price)
        token = last_name(label or "")
        if price is None or len(token) < 3:
            continue
        for position, (name, _implied) in enumerate(named):
            if token in normalize(name).split():
                candidates.append((price, position, label))
                break
    if len(candidates) != 2:
        return None
    price, position, label = max(candidates, key=lambda item: item[0])
    if not (Decimal(0) < price < 1):
        return None
    fee = taker_fee(THETA_RETAIL, PRIMARY_CLIP, price) / PRIMARY_CLIP
    band = "0.85-0.97" if Decimal("0.85") <= price < Decimal("0.97") else "other"
    return {
        "status": "matched",
        "band": band,
        "pm_slug": game.get("slug"),
        "pm_title": game.get("title"),
        "pm_side": label,
        "pinnacle_league": line.get("league"),
        "ask": float(price),
        "proportional_fair": float(prop[position]),
        "power_fair": float(pow_[position]),
        "net_proportional": float(prop[position] - price - fee),
        "net_power": float(pow_[position] - price - fee),
        "fee_per_contract": float(fee),
    }


def main() -> None:
    key = os.environ.get("PINNACLE_GUEST_KEY", "").strip()
    limiter = RateLimiter(1)
    pm_rows = pm_games(limiter)
    print(f"pm games {sum(1 for row in pm_rows if not row.get('error'))}", flush=True)
    if not key:
        payload = {"error": "PINNACLE_GUEST_KEY was not set. Pinnacle cross-section was not run.", "pm_games": len(pm_rows)}
        (ROOT / "results" / "pinnacle_cross.json").write_text(json.dumps(payload, indent=2) + "\n")
        print(payload["error"])
        return
    lines = pinnacle_lines(key, limiter)
    print(f"pinnacle moneylines {len(lines)}", flush=True)
    pairs = match_games([row for row in pm_rows if not row.get("error")], lines)
    priced = []
    for pair in pairs:
        result = side_fair(pair["pm"], pair["line"])
        if result:
            priced.append(result)
    favorites = [row for row in priced if row.get("band") == "0.85-0.97"]
    def _mean(rows: list[dict], field: str) -> float | None:
        if not rows:
            return None
        return float(sum(Decimal(str(row[field])) for row in rows) / Decimal(len(rows)))

    summary = {
        "rules": "PREREG.md T5 pinnacle. Same-day cross-section, not a settlement test. "
        "Only parent matchups with a two-way moneyline are used. An earlier run matched "
        "futures specials, and a second run read league-list side prices that are the yes "
        "bid and yes ask rather than the two outcomes. Both were discarded. Buy-long is the "
        "yes ask and buy-short is one minus the yes bid.",
        "pm_games": sum(1 for row in pm_rows if not row.get("error")),
        "pm_league_errors": [row for row in pm_rows if row.get("error")],
        "pinnacle_moneylines": len(lines),
        "name_matches": len(pairs),
        "priced_matches": len(priced),
        "favorite_band_matches": len(favorites),
        "mean_net_power_all": _mean(priced, "net_power"),
        "mean_net_power_favorite_band": _mean(favorites, "net_power"),
        "mean_net_proportional_favorite_band": _mean(favorites, "net_proportional"),
        "positive_power_favorite_band": sum(1 for row in favorites if row["net_power"] > 0),
        "rows": priced,
    }
    (ROOT / "results" / "pinnacle_cross.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: summary[key] for key in summary if key not in {"rows", "pm_league_errors"}}, indent=2))


if __name__ == "__main__":
    main()
