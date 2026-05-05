# odds_fetcher.py
import requests
from config import ODDS_API_KEY

BASE = "https://api.the-odds-api.com/v4"


def get_premier_league_odds() -> list:
    """
    Fetch match odds for upcoming PL fixtures.
    Markets: h2h (match result) and totals (over/under 2.5 goals).
    Note: btts market is not supported on this plan.
    """
    response = requests.get(
        f"{BASE}/sports/soccer_epl/odds",
        params={
            "apiKey": ODDS_API_KEY,
            "regions": "uk",
            "markets": "h2h,totals",
            "oddsFormat": "decimal",
            "dateFormat": "iso"
        },
        timeout=10
    )
    response.raise_for_status()
    return response.json()


def build_team_odds_map(odds_data: list) -> dict[str, dict]:
    """
    Build a map of team_name -> odds signals.
    Averages across all bookmakers for consensus probabilities.

    Returns per team:
      - win_prob: consensus implied win probability (0-100)
      - over25_prob: consensus implied probability of over 2.5 goals (0-100)
      - match_total_goals: estimated total goals for the match
      - proj_goals: team's projected goals (split from match total by win prob)
      - cs_prob: estimated clean sheet probability
      - opponent: who they're playing
      - home: whether they're at home
    """
    team_map = {}

    for match in odds_data:
        home_team = match["home_team"]
        away_team = match["away_team"]

        # Collect h2h probabilities across all bookmakers
        home_win_probs, away_win_probs = [], []
        over25_probs = []

        for bookmaker in match.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market["key"] == "h2h":
                    for outcome in market["outcomes"]:
                        p = 1 / outcome["price"] * 100
                        if outcome["name"] == home_team:
                            home_win_probs.append(p)
                        elif outcome["name"] == away_team:
                            away_win_probs.append(p)
                elif market["key"] == "totals":
                    for outcome in market["outcomes"]:
                        if outcome.get("point") == 2.5 and outcome["name"] == "Over":
                            over25_probs.append(1 / outcome["price"] * 100)

        # Consensus (average) probabilities
        home_win = round(sum(home_win_probs) / len(home_win_probs), 1) if home_win_probs else None
        away_win = round(sum(away_win_probs) / len(away_win_probs), 1) if away_win_probs else None
        over25   = round(sum(over25_probs) / len(over25_probs), 1) if over25_probs else None

        # Estimate match total goals from over 2.5 probability
        # Calibrated: 50% over2.5 ≈ 2.5 goals, 70% ≈ 3.1 goals, 30% ≈ 1.9 goals
        if over25 is not None:
            match_goals = round(1.0 + (over25 / 100) * 3.0, 2)
        else:
            match_goals = None

        # Split match goals between teams proportionally to win probability
        # Teams with higher win prob are expected to score more
        if match_goals and home_win and away_win:
            total_win = home_win + away_win  # excludes draw
            home_goals = round(match_goals * (home_win / total_win), 2)
            away_goals = round(match_goals * (away_win / total_win), 2)
        else:
            home_goals = None
            away_goals = None

        # CS probability: based on opponent's projected goals
        # Lower opp goals = higher CS chance
        # Calibrated: 0.8 opp goals ≈ 45% CS, 1.5 ≈ 30%, 2.0 ≈ 18%
        def cs_from_goals(opp_goals):
            if opp_goals is None:
                return None
            return round(max(0, 55 - opp_goals * 22), 1)

        team_map[home_team] = {
            "win_prob":          home_win,
            "over25_prob":       over25,
            "match_goals":       match_goals,
            "proj_goals":        home_goals,
            "cs_prob":           cs_from_goals(away_goals),
            "opponent":          away_team,
            "home":              True,
        }
        team_map[away_team] = {
            "win_prob":          away_win,
            "over25_prob":       over25,
            "match_goals":       match_goals,
            "proj_goals":        away_goals,
            "cs_prob":           cs_from_goals(home_goals),
            "opponent":          home_team,
            "home":              False,
        }

    return team_map


def get_clean_sheet_probability(odds_data: list, team_name: str) -> float | None:
    """
    Estimate clean sheet probability from the opponent's win probability.
    Lower opponent win prob = higher chance of a clean sheet.
    This is an approximation since btts market is unavailable on this plan.
    """
    for match in odds_data:
        home_team = match["home_team"]
        away_team = match["away_team"]

        is_home = team_name.lower() in home_team.lower()
        is_away = team_name.lower() in away_team.lower()
        if not is_home and not is_away:
            continue

        opponent = away_team if is_home else home_team

        for bookmaker in match.get("bookmakers", [])[:1]:
            for market in bookmaker.get("markets", []):
                if market["key"] == "h2h":
                    for outcome in market["outcomes"]:
                        if outcome["name"] == opponent:
                            # Rough CS proxy: inverse of opponent win probability
                            opp_win_prob = 1 / outcome["price"]
                            return round((1 - opp_win_prob) * 100, 1)
    return None


def parse_odds_for_display(odds_data: list) -> list[dict]:
    """
    Parse raw odds into a clean list for display.
    """
    matches = []
    for match in odds_data:
        parsed = {
            "home":     match["home_team"],
            "away":     match["away_team"],
            "kickoff":  match["commence_time"],
            "h2h":      None,
            "over_2_5": None,
        }

        for bookmaker in match.get("bookmakers", [])[:1]:
            for market in bookmaker.get("markets", []):
                if market["key"] == "h2h":
                    parsed["h2h"] = {
                        o["name"]: o["price"]
                        for o in market["outcomes"]
                    }
                elif market["key"] == "totals":
                    for outcome in market["outcomes"]:
                        if outcome.get("point") == 2.5 and outcome["name"] == "Over":
                            parsed["over_2_5"] = outcome["price"]

        matches.append(parsed)
    return matches