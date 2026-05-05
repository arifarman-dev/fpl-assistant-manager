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

    free_transfers = calculate_free_transfers(team_id, current_gw)
    print(f"  ✅ Free transfers: {free_transfers}")

    chip_status = get_chip_status(team_id)
    print(f"  ✅ Chips used: {chip_status['used']}")
    print(f"  ✅ Chips available: {chip_status['available']}")

    return {
        "bootstrap":      bootstrap,
        "fixtures":       fixtures,
        "team_info":      team_info,
        "picks":          picks,
        "current_gw":     current_gw,
        "free_transfers": free_transfers,
        "chip_status":    chip_status
    }


def calculate_free_transfers(team_id: int, current_gw: int) -> int:
    """
    Simulate FT bank across the season by replaying each GW.
    
    FPL rules:
    - Start season with 1 FT
    - Each GW: bank = max(0, bank - free_transfers_used) + 1
    - Wildcard: you get 1 FT next GW (bank resets to 1 after use)
    - Free Hit: your real team FT bank is untouched
    - Taking a hit: costs 4pts per extra transfer, bank resets to 1 next GW
    - No evidence of a hard cap below 3 based on observed FPL behaviour
    """
    try:
        response = requests.get(
            f"{FPL_BASE_URL}/entry/{team_id}/history/",
            headers=FPL_HEADERS,
            timeout=10
        )
        response.raise_for_status()
        history = response.json()

        gw_history = sorted(
            history.get("current", []),
            key=lambda x: x["event"]
        )
        chips_used = {
            c["event"]: c["name"]
            for c in history.get("chips", [])
        }

        if not gw_history:
            return 1

        # ft_bank = free transfers available at the START of each GW
        ft_bank = 1
        prev_gw_num = None

        for i, gw in enumerate(gw_history):
            gw_num = gw["event"]
            made   = gw["event_transfers"]
            cost   = gw["event_transfers_cost"]
            chip   = chips_used.get(gw_num, "")

            if gw_num == current_gw:
                # Current GW — subtract transfers made, don't add +1
                if cost == 0:
                    ft_bank = max(0, ft_bank - made)
                else:
                    ft_bank = 0
                break

            # Past GW — simulate the FT bank change
            if chip == "freehit":
                # Real team FT bank unaffected, carries over + 1 for next GW
                ft_bank = ft_bank + 1
            elif chip == "wildcard":
                # Resets to 1 next GW
                ft_bank = 2  # 1 reset + 1 for next GW
            elif cost > 0:
                # Hit taken — resets to 1 next GW
                ft_bank = 2
            else:
                # Normal GW
                ft_bank = max(0, ft_bank - made) + 1

            prev_gw_num = gw_num

        # If current GW not in history yet, subtract the extra +1
        # added in the last past GW iteration
        current_gw_in_history = any(
            g["event"] == current_gw for g in gw_history
        )
        if not current_gw_in_history:
            ft_bank = max(1, ft_bank - 1)

        print(f"DEBUG FT: current_gw={current_gw}, "
              f"in_history={current_gw_in_history}, "
              f"ft_bank={ft_bank}")

        return max(1, ft_bank)

    except Exception:
        return 1

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

def get_chip_status(team_id: int) -> dict:
    """
    Fetch which chips have been used and which are still available.
    
    FPL chip names in the API:
    - 'wildcard'  — used for BOTH wildcards (appears twice if both used)
    - 'freehit'   — free hit
    - 'bboost'    — bench boost  
    - '3xc'       — triple captain
    
    FPL allows:
    - 2x wildcard (one per half of season)
    - 1x free hit
    - 1x bench boost
    - 1x triple captain
    """
    try:
        response = requests.get(
            f"{FPL_BASE_URL}/entry/{team_id}/history/",
            headers=FPL_HEADERS,
            timeout=10
        )
        response.raise_for_status()
        history = response.json()

        # Count how many times each chip has been used
        chip_counts = {}
        chip_gws = {}
        for chip in history.get("chips", []):
            name = chip["name"]
            chip_counts[name] = chip_counts.get(name, 0) + 1
            if name not in chip_gws:
                chip_gws[name] = []
            chip_gws[name].append(chip["event"])

        used = []
        available = []

        # Wildcard: allowed twice, once per half season
        wc_used = chip_counts.get("wildcard", 0)
        if wc_used >= 2:
            used.append("Wildcard (both used)")
        elif wc_used == 1:
            gw_used = chip_gws["wildcard"][0]
            if gw_used <= 19:
                used.append(f"Wildcard 1 (used GW{gw_used})")
                available.append("Wildcard 2 (second half of season)")
            else:
                used.append(f"Wildcard 2 (used GW{gw_used})")
                available.append("Wildcard 1 (first half — no longer available)")
        else:
            available.append("Wildcard 1")
            available.append("Wildcard 2")

        # Single-use chips
        single_chips = {
            "freehit": "Free Hit",
            "bboost":  "Bench Boost",
            "3xc":     "Triple Captain"
        }
        for chip_key, chip_name in single_chips.items():
            if chip_counts.get(chip_key, 0) >= 1:
                gw = chip_gws[chip_key][0]
                used.append(f"{chip_name} (used GW{gw})")
            else:
                available.append(chip_name)

        return {
            "used":     used,
            "available": available,
            "raw_counts": chip_counts
        }

    except Exception:
        return {"used": [], "available": [], "raw_counts": {}}