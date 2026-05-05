import pandas as pd
from odds_fetcher import get_premier_league_odds, build_team_odds_map

BASE = "https://raw.githubusercontent.com/olbauday/FPL-Core-Insights/main/data/2025-2026"
BASE_GW = BASE + "/By%20Gameweek"

# Map FPL short names -> Odds API full team names
# Odds API uses full names; FPL uses short codes
FPL_TO_ODDS_TEAM = {
    "ARS": "Arsenal",
    "AVL": "Aston Villa",
    "BOU": "Bournemouth",
    "BRE": "Brentford",
    "BHA": "Brighton and Hove Albion",
    "BUR": "Burnley",
    "CHE": "Chelsea",
    "CRY": "Crystal Palace",
    "EVE": "Everton",
    "FUL": "Fulham",
    "IPS": "Ipswich Town",
    "LEE": "Leeds United",
    "LEI": "Leicester City",
    "LIV": "Liverpool",
    "MCI": "Manchester City",
    "MUN": "Manchester United",
    "NEW": "Newcastle United",
    "NFO": "Nottingham Forest",
    "SOU": "Southampton",
    "SUN": "Sunderland",
    "TOT": "Tottenham Hotspur",
    "WHU": "West Ham United",
    "WOL": "Wolverhampton Wanderers",
}


def get_latest_gw_from_stats() -> int:
    """Find the most recent gameweek available in playerstats."""
    stats = pd.read_csv(f"{BASE}/playerstats.csv")
    return int(stats["gw"].max())


def get_enriched_player_stats(current_gw: int) -> pd.DataFrame:
    """
    Pull current player stats from GitHub dataset.
    Returns one row per player with xG, xA, chance of playing, and news.
    """
    stats = pd.read_csv(f"{BASE}/playerstats.csv")
    current = stats[stats["gw"] == current_gw].copy()

    keep_cols = [
        "id", "web_name",
        "expected_goals", "expected_assists", "expected_goal_involvements",
        "expected_goals_per_90", "expected_assists_per_90",
        "expected_goal_involvements_per_90",
        "chance_of_playing_next_round", "chance_of_playing_this_round",
        "news",
        "points_per_game",
        "ict_index", "influence", "creativity", "threat",
        "penalties_order", "direct_freekicks_order",
        "corners_and_indirect_freekicks_order",
        "defensive_contribution_per_90",
        "starts_per_90",
    ]
    available_cols = [c for c in keep_cols if c in current.columns]
    return current[available_cols].reset_index(drop=True)


def get_team_elo() -> dict[str, float]:
    """
    Return a dict mapping team short_name -> Elo rating.
    Used to compute Elo-weighted fixture difficulty.
    """
    teams = pd.read_csv(f"{BASE}/teams.csv")
    return dict(zip(teams["short_name"], teams["elo"]))


def get_team_strength_breakdown() -> pd.DataFrame:
    """
    Return full team strength breakdown including attack/defence home/away.
    """
    return pd.read_csv(f"{BASE}/teams.csv")


def get_recent_gw_performance(current_gw: int, n_gws: int = 5) -> pd.DataFrame:
    """
    Pull player performance across the last N gameweeks.
    Returns average xG per 90, xA per 90, and points per game over that window.
    Useful for identifying in-form players the FPL form metric might lag on.
    """
    all_gws = []
    for gw in range(max(1, current_gw - n_gws + 1), current_gw + 1):
        try:
            gw_df = pd.read_csv(f"{BASE_GW}/GW{gw}/player_gameweek_stats.csv")
            gw_df["gw"] = gw
            all_gws.append(gw_df)
        except Exception:
            continue

    if not all_gws:
        return pd.DataFrame()

    combined = pd.concat(all_gws, ignore_index=True)

    agg = combined.groupby("web_name").agg(
        avg_xg_per90=("expected_goals_per_90", "mean"),
        avg_xa_per90=("expected_assists_per_90", "mean"),
        avg_points=("event_points", "mean"),
        avg_minutes=("minutes", "mean"),
        gws_played=("gw", "count")
    ).reset_index()

    return agg


def enrich_context(context: dict, current_gw: int) -> dict:
    """
    Master enrichment function. Adds xG, xA, Elo, chance of playing,
    and betting odds (win probability, over 2.5 goals) to the context.
    """
    print("  Fetching enrichment data...")

    # 1. Fetch all external data
    player_stats = get_enriched_player_stats(current_gw)
    elo_map = get_team_elo()
    recent_form = get_recent_gw_performance(current_gw, n_gws=5)

    # 2. Fetch odds and build team-level signals
    odds_map = {}  # fpl_short_name -> {win_prob, over25_prob, opponent, home}
    try:
        odds_data = get_premier_league_odds()
        raw_odds_map = build_team_odds_map(odds_data)
        # Translate odds API team names back to FPL short names
        odds_name_to_fpl = {v: k for k, v in FPL_TO_ODDS_TEAM.items()}
        for odds_name, signals in raw_odds_map.items():
            fpl_short = odds_name_to_fpl.get(odds_name)
            if fpl_short:
                odds_map[fpl_short] = signals
        print("  ✅ External data fetched (xG, Elo, Recent Form, Odds)")
    except Exception as e:
        print(f"  ⚠️  Odds fetch failed ({e}), continuing without odds")
        print("  ✅ External data fetched (xG, Elo, Recent Form)")

    def attach_odds(df: pd.DataFrame) -> pd.DataFrame:
        """Add win_prob and over25_prob columns based on player's team."""
        df = df.copy()
        df["win_prob"]    = df["team"].map(
            lambda t: odds_map.get(t, {}).get("win_prob")
        )
        df["over25_prob"] = df["team"].map(
            lambda t: odds_map.get(t, {}).get("over25_prob")
        )
        return df

    # 3. Enrich the SQUAD
    squad = context["squad"].copy()
    squad = squad.rename(columns={"name": "web_name"})
    squad = squad.merge(
        player_stats[["web_name", "expected_goals_per_90", "expected_assists_per_90",
                      "chance_of_playing_next_round", "news", "ict_index",
                      "penalties_order", "starts_per_90"]],
        on="web_name", how="left"
    )
    squad = squad.merge(
        recent_form[["web_name", "avg_xg_per90", "avg_xa_per90",
                     "avg_points", "gws_played"]],
        on="web_name", how="left"
    )
    squad = attach_odds(squad)
    context["squad"] = squad.rename(columns={"web_name": "name"})

    # 4. Enrich the CANDIDATES
    enriched_candidates = {}
    for pos, df in context["candidates"].items():
        df = df.copy()
        df = df.rename(columns={"name": "web_name"})
        df = df.merge(
            player_stats[["web_name", "expected_goals_per_90",
                          "expected_assists_per_90",
                          "chance_of_playing_next_round",
                          "ict_index", "penalties_order", "starts_per_90"]],
            on="web_name", how="left"
        )
        df = df.merge(
            recent_form[["web_name", "avg_xg_per90", "avg_xa_per90", "avg_points"]],
            on="web_name", how="left"
        )
        df = attach_odds(df)
        enriched_candidates[pos] = df.rename(columns={"web_name": "name"})

    context["candidates"] = enriched_candidates
    context["elo_map"] = elo_map
    context["odds_map"] = odds_map

    print("  🚀 Context enrichment complete.")
    return context