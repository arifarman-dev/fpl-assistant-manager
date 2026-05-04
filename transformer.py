import pandas as pd
from config import FPL_HEADERS


POSITION_MAP = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def build_fixture_difficulty(fixtures: list, next_n_gws: int = 5) -> dict[int, list[int]]:
    """
    Build a dict mapping team_id -> list of FDR ratings for next N gameweeks.
    Only includes unfinished fixtures.
    """
    upcoming = [f for f in fixtures if not f["finished"] and f["event"] is not None]
    upcoming_sorted = sorted(upcoming, key=lambda x: x["event"])

    difficulty = {}
    for fixture in upcoming_sorted:
        home_team = fixture["team_h"]
        away_team = fixture["team_a"]
        home_fdr = fixture["team_h_difficulty"]
        away_fdr = fixture["team_a_difficulty"]

        if home_team not in difficulty:
            difficulty[home_team] = []
        if away_team not in difficulty:
            difficulty[away_team] = []

        if len(difficulty[home_team]) < next_n_gws:
            difficulty[home_team].append(home_fdr)
        if len(difficulty[away_team]) < next_n_gws:
            difficulty[away_team].append(away_fdr)

    return difficulty


def build_player_dataframe(bootstrap: dict, fixtures: list) -> pd.DataFrame:
    """
    Build a clean DataFrame of all 830 players with relevant stats.
    """
    difficulty = build_fixture_difficulty(fixtures, next_n_gws=5)
    team_map = {t["id"]: t["short_name"] for t in bootstrap["teams"]}

    rows = []
    for p in bootstrap["elements"]:
        fdrs = difficulty.get(p["team"], [])
        avg_fdr = round(sum(fdrs) / len(fdrs), 2) if fdrs else None
        fdr_str = " / ".join(str(d) for d in fdrs) if fdrs else "n/a"

        rows.append({
            "id":               p["id"],
            "name":             p["web_name"],
            "team":             team_map.get(p["team"], "UNK"),
            "position":         POSITION_MAP.get(p["element_type"], "UNK"),
            "price":            p["now_cost"] / 10,
            "form":             float(p["form"] or 0),
            "ep_next":          float(p["ep_next"] or 0),
            "total_points":     p["total_points"],
            "minutes":          p["minutes"],
            "selected_pct":     float(p["selected_by_percent"] or 0),
            "transfers_in_gw":  p["transfers_in_event"],
            "status":           p["status"],
            "news":             p["news"],
            "fdrs":             fdr_str,
            "avg_fdr":          avg_fdr,
        })

    df = pd.DataFrame(rows)
    return df


def get_squad(picks: dict, player_df: pd.DataFrame) -> pd.DataFrame:
    """
    Return a DataFrame of the manager's current 15-player squad.
    """
    pick_map = {p["element"]: p for p in picks["picks"]}
    squad_ids = list(pick_map.keys())
    squad = player_df[player_df["id"].isin(squad_ids)].copy()

    squad["is_captain"] = squad["id"].apply(
        lambda x: pick_map[x]["is_captain"]
    )
    squad["pick_position"] = squad["id"].apply(
        lambda x: pick_map[x]["position"]
    )
    return squad.sort_values("pick_position").reset_index(drop=True)


def get_transfer_candidates(
    squad: pd.DataFrame,
    player_df: pd.DataFrame,
    bank: float,
    top_n: int = 10
) -> dict[str, pd.DataFrame]:
    """
    For each position, find the top N affordable transfer candidates
    not already in the squad. Ranked by a weighted score.
    Excludes unavailable players (injured/suspended).
    """
    squad_ids = set(squad["id"])
    available = player_df[
        (~player_df["id"].isin(squad_ids)) &
        (player_df["status"] == "a") &
        (player_df["minutes"] > 0)
    ].copy()

    # Weighted score: form and ep_next are the strongest signals,
    # avg_fdr inverted so lower difficulty = higher score
    available["score"] = (
        available["form"] * 0.4 +
        available["ep_next"] * 0.4 +
        (6 - available["avg_fdr"].fillna(3)) * 0.2
    )

    candidates = {}
    for position in ["GK", "DEF", "MID", "FWD"]:
        pos_players = squad[squad["position"] == position]
        if pos_players.empty:
            continue

        # Budget: most expensive player in position + bank
        max_price = pos_players["price"].max() + bank

        pos_candidates = available[
            (available["position"] == position) &
            (available["price"] <= max_price)
        ].sort_values("score", ascending=False).head(top_n)

        candidates[position] = pos_candidates

    return candidates


def build_recommendation_context(
    team_info: dict,
    picks: dict,
    bootstrap: dict,
    fixtures: list
) -> dict:
    player_df = build_player_dataframe(bootstrap, fixtures)
    squad = get_squad(picks, player_df)
    bank = picks["entry_history"]["bank"] / 10

    # Free transfers available
    free_transfers = picks["entry_history"].get("event_transfers_cost", 0)
    # FPL stores free transfers in the picks response
    active_chip = picks.get("active_chip", None)

    candidates = get_transfer_candidates(squad, player_df, bank)

    return {
        "manager":        f"{team_info['player_first_name']} {team_info['player_last_name']}",
        "team_name":      team_info["name"],
        "bank":           bank,
        "free_transfers": picks["entry_history"].get("bank", 1),
        "active_chip":    active_chip,
        "squad":          squad,
        "candidates":     candidates,
        "player_df":      player_df,
    }

def find_differentials(
    player_df: pd.DataFrame,
    current_gw: int,
    max_ownership: float = 15.0,
    min_form: float = 5.0,
    top_n: int = 10
) -> pd.DataFrame:
    """
    Find high-form, low-ownership players — the differentials
    top managers are quietly targeting.
    """
    diffs = player_df[
        (player_df["selected_pct"] <= max_ownership) &
        (player_df["form"] >= min_form) &
        (player_df["status"] == "a") &
        (player_df["minutes"] > 0)
    ].copy()

    diffs["differential_score"] = (
        diffs["form"] * 0.4 +
        diffs["ep_next"] * 0.4 +
        (6 - diffs["avg_fdr"].fillna(3)) * 0.2 -
        diffs["selected_pct"] * 0.05  # penalise high ownership
    )

    return diffs.sort_values(
        "differential_score", ascending=False
    ).head(top_n)[[
        "name", "team", "position", "price",
        "form", "ep_next", "selected_pct", "fdrs",
        "differential_score"
    ]]