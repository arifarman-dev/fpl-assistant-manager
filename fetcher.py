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
    bootstrap = get_bootstrap()
    print("  ✅ Bootstrap data fetched")

    fixtures = get_fixtures()
    print("  ✅ Fixtures fetched")

    team_info = get_team_info(team_id)
    print("  ✅ Team info fetched")

    current_gw = get_current_gameweek(bootstrap)
    picks = get_team_picks(team_id, current_gw)
    print(f"  ✅ GW{current_gw} picks fetched")

    # Auto-detect free transfers
    free_transfers = calculate_free_transfers(picks, team_info, current_gw)
    print(f"  ✅ Free transfers: {free_transfers}")

    return {
        "bootstrap": bootstrap,
        "fixtures": fixtures,
        "team_info": team_info,
        "picks": picks,
        "current_gw": current_gw,
        "free_transfers": free_transfers
    }


def calculate_free_transfers(picks: dict, team_info: dict, current_gw: int) -> int:
    """
    Calculate free transfers available this gameweek.
    FPL logic: you get 1 per week, unused rolls over (max 2).
    Transfers already made this GW are subtracted.
    """
    # Transfers made this GW so far
    transfers_made = picks["entry_history"].get("event_transfers", 0)
    # Cost this GW — if >0, manager already burned into paid transfers
    transfers_cost = picks["entry_history"].get("event_transfers_cost", 0)

    # If they've paid for transfers, all free ones are already used
    if transfers_cost > 0:
        return 0

    # FPL stores the limit in the picks response
    # Max is 2 (1 rolled + 1 this week), min is 1
    # We infer: if no transfers made and bank suggests rolling, it's 2
    # The most reliable signal is entry_history limit field
    limit = picks["entry_history"].get("event_transfers", 1)

    # Calculate remaining free transfers
    # Check if last GW transfers were used — if not, they rolled over
    last_gw_data = team_info.get("current_event", current_gw)
    
    # Conservative approach: use picks data directly
    # FPL gives us transfers_made, we know max is 2
    available = max(1, 2 - transfers_made) if transfers_cost == 0 else 0
    return min(available, 2)

def get_free_transfers(picks: dict) -> int:
    """
    Extract number of free transfers available this gameweek.
    FPL gives 1 per week, max 2 if unused last week.
    """
    # event_transfers is how many have been made
    # We infer available FTs from the picks entry_history
    transfers_made = picks["entry_history"].get("event_transfers", 0)
    transfers_cost = picks["entry_history"].get("event_transfers_cost", 0)

    # If cost is 0, all transfers so far were free
    # FPL max bank of free transfers is 2
    # We read the stored value directly
    return picks.get("transfers", {}).get("limit", 1)

def get_transfer_info(team_id: int) -> dict:
    """Fetch transfer history to calculate free transfers available."""
    response = requests.get(
        f"{FPL_BASE_URL}/entry/{team_id}/transfers/",
        headers=FPL_HEADERS,
        timeout=10
    )
    response.raise_for_status()
    transfers = response.json()
    return transfers