# fetcher.py
import requests
from config import FPL_BASE_URL, FPL_HEADERS


def get_bootstrap() -> dict:
    """Fetch all player and team data from FPL."""
    response = requests.get(
        f"{FPL_BASE_URL}/bootstrap-static/",
        headers=FPL_HEADERS,
        timeout=10
    )
    response.raise_for_status()
    return response.json()


def get_fixtures() -> list:
    """Fetch all fixtures for the season."""
    response = requests.get(
        f"{FPL_BASE_URL}/fixtures/",
        headers=FPL_HEADERS,
        timeout=10
    )
    response.raise_for_status()
    return response.json()


def get_team_info(team_id: int) -> dict:
    """Fetch manager and team summary for a given team ID."""
    response = requests.get(
        f"{FPL_BASE_URL}/entry/{team_id}/",
        headers=FPL_HEADERS,
        timeout=10
    )
    response.raise_for_status()
    return response.json()


def get_team_picks(team_id: int, gameweek: int) -> dict:
    """Fetch the 15-player squad for a specific gameweek."""
    response = requests.get(
        f"{FPL_BASE_URL}/entry/{team_id}/event/{gameweek}/picks/",
        headers=FPL_HEADERS,
        timeout=10
    )
    response.raise_for_status()
    return response.json()


def get_current_gameweek(bootstrap: dict) -> int:
    """Extract the current gameweek number from bootstrap data."""
    for event in bootstrap["events"]:
        if event["is_current"]:
            return event["id"]
    # If between gameweeks, fall back to next
    for event in bootstrap["events"]:
        if event["is_next"]:
            return event["id"]
    raise ValueError("Could not determine current gameweek from bootstrap data")


def fetch_all(team_id: int) -> dict:
    """
    Master fetch function — pulls all data needed for a recommendation.
    Returns a single dict with bootstrap, fixtures, team info, and picks.
    """
    print(f"Fetching FPL data for team {team_id}...")

    bootstrap = get_bootstrap()
    print("  ✅ Bootstrap data fetched")

    fixtures = get_fixtures()
    print("  ✅ Fixtures fetched")

    team_info = get_team_info(team_id)
    print("  ✅ Team info fetched")

    current_gw = get_current_gameweek(bootstrap)
    picks = get_team_picks(team_id, current_gw)
    print(f"  ✅ GW{current_gw} picks fetched")

    return {
        "bootstrap": bootstrap,
        "fixtures": fixtures,
        "team_info": team_info,
        "picks": picks,
        "current_gw": current_gw
    }