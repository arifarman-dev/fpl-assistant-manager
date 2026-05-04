# odds_fetcher.py
import requests
from config import ODDS_API_KEY

BASE = "https://api.the-odds-api.com/v4"

def get_premier_league_odds() -> list:
    """
    Fetch match odds for upcoming PL fixtures.
    Returns clean sheet and goals markets.
    """
    response = requests.get(
        f"{BASE}/sports/soccer_epl/odds",
        params={
            "apiKey": ODDS_API_KEY,
            "regions": "uk",
            "markets": "h2h,totals,btts",
            "oddsFormat": "decimal",
            "dateFormat": "iso"
        },
        timeout=10
    )
    response.raise_for_status()
    return response.json()


def get_clean_sheet_probability(odds_data: list, team_name: str) -> float | None:
    """
    Estimate clean sheet probability from BTTS (both teams to score) odds.
    If BTTS No is priced at 2.0, implied probability of clean sheet = 50%.
    """
    for match in odds_data:
        teams = [match["home_team"], match["away_team"]]
        if not any(team_name.lower() in t.lower() for t in teams):
            continue

        for bookmaker in match.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market["key"] == "btts":
                    for outcome in market["outcomes"]:
                        if outcome["name"] == "No":
                            # Implied probability
                            return round(1 / outcome["price"] * 100, 1)
    return None


def parse_odds_for_display(odds_data: list) -> list[dict]:
    """
    Parse raw odds into a clean list for display.
    """
    matches = []
    for match in odds_data:
        parsed = {
            "home": match["home_team"],
            "away": match["away_team"],
            "kickoff": match["commence_time"],
            "h2h": None,
            "over_2_5": None,
            "btts_yes": None,
        }

        for bookmaker in match.get("bookmakers", [])[:1]:  # take first bookmaker
            for market in bookmaker.get("markets", []):
                if market["key"] == "h2h":
                    outcomes = {o["name"]: o["price"]
                                for o in market["outcomes"]}
                    parsed["h2h"] = outcomes

                elif market["key"] == "totals":
                    for outcome in market["outcomes"]:
                        if outcome["point"] == 2.5 and outcome["name"] == "Over":
                            parsed["over_2_5"] = outcome["price"]

                elif market["key"] == "btts":
                    for outcome in market["outcomes"]:
                        if outcome["name"] == "Yes":
                            parsed["btts_yes"] = outcome["price"]

        matches.append(parsed)
    return matches