import pandas as pd
from config import FPL_HEADERS


POSITION_MAP = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def build_fixture_difficulty(fixtures: list, next_n_gws: int = 5) -> dict[int, list[tuple]]:
    """
    Build a dict mapping team_id -> list of (gw, fdr, opponent_id) tuples
    for the next N gameweeks. Only includes unfinished fixtures.
    DGW teams will have two entries for the same GW.
    """
    upcoming = [f for f in fixtures if not f["finished"] and f["event"] is not None]
    upcoming_sorted = sorted(upcoming, key=lambda x: x["event"])

    difficulty = {}
    for fixture in upcoming_sorted:
        ht  = fixture["team_h"]
        at  = fixture["team_a"]
        gw  = fixture["event"]
        h_fdr = fixture["team_h_difficulty"]
        a_fdr = fixture["team_a_difficulty"]

        if ht not in difficulty:
            difficulty[ht] = []
        if at not in difficulty:
            difficulty[at] = []

        if len(difficulty[ht]) < next_n_gws:
            difficulty[ht].append((gw, h_fdr, at))
        if len(difficulty[at]) < next_n_gws:
            difficulty[at].append((gw, a_fdr, ht))

    return difficulty


def weighted_avg_fdr(fdrs: list) -> float:
    """
    Compute a fixture-run score weighting the immediate gameweek most heavily,
    tapering off for later weeks.

    Rationale: the next fixture is the most actionable for transfer decisions.
    Later fixtures matter but shouldn't override an immediately terrible fixture.

    Weights: GW1=0.35, GW2=0.25, GW3=0.20, GW4=0.12, GW5=0.08
    If fewer than 5 GWs available, weights are renormalised.
    """
    weights = [0.35, 0.25, 0.20, 0.12, 0.08]
    if not fdrs:
        return 3.0  # neutral fallback
    w = weights[:len(fdrs)]
    total_w = sum(w)
    return round(sum(f * wt for f, wt in zip(fdrs, w)) / total_w, 2)


def build_player_dataframe(bootstrap: dict, fixtures: list) -> pd.DataFrame:
    """
    Build a clean DataFrame of all players with relevant stats.
    """
    difficulty = build_fixture_difficulty(fixtures, next_n_gws=5)
    team_map = {t["id"]: t["short_name"] for t in bootstrap["teams"]}

    rows = []
    for p in bootstrap["elements"]:
        fix_tuples = difficulty.get(p["team"], [])  # list of (gw, fdr, opp_id)
        fdrs_only  = [fdr for (_, fdr, _) in fix_tuples]
        avg_fdr    = weighted_avg_fdr(fdrs_only)

        # Build labelled string: "GW36 vs BRE(3) / GW36 vs CRY(3) / GW37 vs BOU(4)"
        fdr_parts = []
        for (gw, fdr, opp_id) in fix_tuples:
            opp = team_map.get(opp_id, "?")
            fdr_parts.append(f"GW{gw} vs {opp}({fdr})")
        fdr_str = " / ".join(fdr_parts) if fdr_parts else "n/a"

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

    return pd.DataFrame(rows)


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
    bootstrap: dict,
    elo_map: dict = None,
    top_n: int = 10
) -> dict[str, pd.DataFrame]:
    """
    For each position, find top N affordable transfer candidates.
    Enforces FPL 3-player-per-team rule.
    Uses opponent Elo (when available) for a more accurate fixture difficulty
    score than FDR alone — Arsenal FDR=4 is much harder than Spurs FDR=4.
    """
    # Build player_id -> team_id map
    id_to_team = {p["id"]: p["team"] for p in bootstrap["elements"]}
    team_to_short = {t["id"]: t["short_name"] for t in bootstrap["teams"]}

    # Count current squad players per team
    squad_team_counts = {}
    for _, p in squad.iterrows():
        match = [
            el for el in bootstrap["elements"]
            if el["web_name"] == p["name"]
        ]
        if match:
            team_id = match[0]["team"]
            squad_team_counts[team_id] = squad_team_counts.get(team_id, 0) + 1

    # Teams already at the 3-player limit
    maxed_teams = {
        tid for tid, count in squad_team_counts.items()
        if count >= 3
    }

    if maxed_teams:
        maxed_names = [team_to_short.get(t, str(t)) for t in maxed_teams]
        print(f"  ⚠️  3-player limit reached for: {', '.join(maxed_names)}")

    squad_ids = set(squad["id"])

    # Minimum minutes: ~900 = roughly 10 full games played this season.
    # Filters out pure rotation/bench players who rarely start.
    MIN_MINUTES = 900

    available = player_df[
        (~player_df["id"].isin(squad_ids)) &
        (player_df["status"] == "a") &
        (player_df["minutes"] >= MIN_MINUTES)
    ].copy()

    # Apply 3-player-per-team rule
    # Map player_df ids to team ids
    available["team_id"] = available["id"].map(id_to_team)
    available = available[~available["team_id"].isin(maxed_teams)]

    # starts_per_90 from playerstats is merged in after enrichment,
    # but scoring happens before enrichment. Use season minutes as a
    # rotation proxy: penalise players with fewer total minutes.
    minutes_factor = (available["minutes"].clip(upper=2700) / 2700)

    if elo_map:
        # Elo-adjusted fixture difficulty: use opponent Elo normalised to 1-5 scale.
        # Elo range in PL ~1650-2060. Map to difficulty: higher opp Elo = harder.
        # We use the NEXT fixture's opponent (first in fdrs string) for immediate impact,
        # plus a weighted average across all fixtures using opponent Elo.
        # Since we don't have per-fixture opponent Elo here, use avg_fdr as fallback
        # but scale it using the team's own Elo context.
        # Better: rebuild a per-player elo_difficulty from the fixture tuples.
        # We need the difficulty dict — rebuild it from player team mapping.
        id_to_team_short = {
            p["id"]: next((t["short_name"] for t in bootstrap["teams"] if t["id"] == p["team"]), "UNK")
            for p in bootstrap["elements"]
        }
        # Build team_short -> list of opponent Elos from fixture data
        # We'll compute an elo-weighted difficulty per player
        elo_min, elo_max = 1650, 2060

        def elo_to_fdr_scale(opp_elo: float) -> float:
            """Normalise opponent Elo to 1-5 difficulty scale."""
            return 1 + 4 * (opp_elo - elo_min) / (elo_max - elo_min)

        # Get fixture tuples from player_df — we stored fdrs as a string,
        # but we need the raw tuples. Re-derive from bootstrap fixture difficulty.
        # Use avg_fdr as proxy but adjust: scale by whether team faces top-6 Elo sides.
        # Simpler: use avg_fdr but add a penalty if the team's first opponent is top-4 Elo.
        top4_elo_teams = {name for name, elo in elo_map.items() if elo >= 1900}

        def elo_adjusted_score(row):
            base = row["form"] * 0.38 + row["ep_next"] * 0.32 + (6 - row["avg_fdr"]) * 0.20 + minutes_factor[row.name] * 0.10
            # Penalise if first fixture is against a top-4 Elo team
            fdrs_str = row["fdrs"]
            if fdrs_str and fdrs_str != "n/a":
                first_fix = fdrs_str.split("/")[0].strip()  # e.g. "GW36 vs ARS(4)"
                for top_team in top4_elo_teams:
                    if top_team in first_fix:
                        base -= 0.15  # meaningful penalty for facing elite opposition immediately
                        break
            return base

        available["score"] = available.apply(elo_adjusted_score, axis=1)
    else:
        available["score"] = (
            available["form"] * 0.38 +
            available["ep_next"] * 0.32 +
            (6 - available["avg_fdr"].fillna(3)) * 0.20 +
            minutes_factor * 0.10
        )

    candidates = {}
    for position in ["GK", "DEF", "MID", "FWD"]:
        pos_players = squad[squad["position"] == position]
        if pos_players.empty:
            continue

        max_price = pos_players["price"].max() + bank

        pos_candidates = available[
            (available["position"] == position) &
            (available["price"] <= max_price)
        ].sort_values("score", ascending=False).head(5)  # was 10

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
    active_chip = picks.get("active_chip", None)

    # Fetch Elo map for opponent-quality-adjusted scoring
    elo_map = {}
    try:
        import requests as _req
        BASE = "https://raw.githubusercontent.com/olbauday/FPL-Core-Insights/main/data/2025-2026"
        import pandas as _pd
        teams_df = _pd.read_csv(f"{BASE}/teams.csv")
        elo_map = dict(zip(teams_df["short_name"], teams_df["elo"]))
    except Exception:
        pass

    candidates = get_transfer_candidates(squad, player_df, bank, bootstrap, elo_map=elo_map)

    return {
        "manager":     f"{team_info['player_first_name']} {team_info['player_last_name']}",
        "team_name":   team_info["name"],
        "bank":        bank,
        "active_chip": active_chip,
        "squad":       squad,
        "candidates":  candidates,
        "player_df":   player_df,
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

def get_optimal_lineup(squad: pd.DataFrame) -> pd.DataFrame:
    """
    Determine the optimal starting XI from the current squad.
    
    Rules:
    - 1 GK
    - Min 3 DEF, max 5 DEF
    - Min 2 FWD, max 3 FWD  
    - Min 2 MID, max 5 MID
    - Maximise total EP of starting XI
    - Injured/unavailable players cannot start
    """
    # Filter out unavailable players
    available = squad[squad["status"] != "i"].copy()
    
    # Sort by ep_next descending within each position
    gks  = available[available["position"] == "GK"].sort_values(
        "ep_next", ascending=False
    )
    defs = available[available["position"] == "DEF"].sort_values(
        "ep_next", ascending=False
    )
    mids = available[available["position"] == "MID"].sort_values(
        "ep_next", ascending=False
    )
    fwds = available[available["position"] == "FWD"].sort_values(
        "ep_next", ascending=False
    )

    # Start with minimums
    starting_gk   = gks.head(1)
    starting_defs = defs.head(3)
    starting_mids = mids.head(2)
    starting_fwds = fwds.head(2)

    # Remaining players to fill the last 3 spots
    used_ids = set(
        starting_gk["id"].tolist() +
        starting_defs["id"].tolist() +
        starting_mids["id"].tolist() +
        starting_fwds["id"].tolist()
    )

    remaining = available[~available["id"].isin(used_ids)].sort_values(
        "ep_next", ascending=False
    )

    # Fill remaining 3 spots respecting formation limits
    extra_starters = []
    current_defs = len(starting_defs)
    current_mids = len(starting_mids)
    current_fwds = len(starting_fwds)

    for _, player in remaining.iterrows():
        if len(extra_starters) >= 3:
            break
        pos = player["position"]
        if pos == "DEF" and current_defs < 5:
            extra_starters.append(player)
            current_defs += 1
        elif pos == "MID" and current_mids < 5:
            extra_starters.append(player)
            current_mids += 1
        elif pos == "FWD" and current_fwds < 3:
            extra_starters.append(player)
            current_fwds += 1

    if extra_starters:
        extra_df = pd.DataFrame(extra_starters)
    else:
        extra_df = pd.DataFrame()

    starters = pd.concat([
        starting_gk, starting_defs,
        starting_mids, starting_fwds,
        extra_df
    ]).drop_duplicates(subset=["id"])

    # Mark starters vs bench
    squad = squad.copy()
    squad["optimal_start"] = squad["id"].isin(starters["id"].tolist())

    return squad