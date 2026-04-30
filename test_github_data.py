import pandas as pd

BASE = "https://raw.githubusercontent.com/olbauday/FPL-Core-Insights/main/data/2025-2026"
BASE_GW = BASE + "/By%20Gameweek"

print("=== Testing FPL Core Insights Data v2 ===\n")

# Test 1: Latest player stats (filter to most recent GW only)
try:
    stats = pd.read_csv(f"{BASE}/playerstats.csv")
    latest_gw = stats["gw"].max()
    current_stats = stats[stats["gw"] == latest_gw].copy()
    print(f"✅ playerstats.csv — latest GW: {latest_gw}, players: {len(current_stats)}")
    
    # Top 5 by xG (current season, deduplicated)
    top_xg = current_stats.nlargest(5, "expected_goals")[
        ["web_name", "expected_goals", "expected_assists", "form", "total_points"]
    ]
    print(f"\n   Top 5 by xG (GW{latest_gw}):")
    print(top_xg.to_string(index=False))

    # Check chance_of_playing columns
    print(f"\n   Chance of playing columns present: "
          f"{'chance_of_playing_next_round' in current_stats.columns}")
    
    # Show Salah and Xavi specifically
    targets = current_stats[current_stats["web_name"].isin(["M.Salah", "Xavi"])]
    if not targets.empty:
        print(f"\n   Salah/Xavi availability data:")
        print(targets[["web_name", "status", "chance_of_playing_next_round", 
                       "chance_of_playing_this_round", "news"]].to_string(index=False))
except Exception as e:
    print(f"❌ playerstats failed: {e}")

print()

# Test 2: Elo ratings with strength breakdown
try:
    teams = pd.read_csv(f"{BASE}/teams.csv")
    print(f"✅ teams.csv — Elo + strength breakdown:")
    cols = ["name", "elo", "strength_attack_home", "strength_attack_away",
            "strength_defence_home", "strength_defence_away"]
    available_cols = [c for c in cols if c in teams.columns]
    print(teams[available_cols].sort_values("elo", ascending=False).to_string(index=False))
except Exception as e:
    print(f"❌ teams.csv failed: {e}")

print()

# Test 3: GW34 gameweek stats (URL encoded)
try:
    gw_stats = pd.read_csv(f"{BASE_GW}/GW34/player_gameweek_stats.csv")
    print(f"✅ GW34 player_gameweek_stats.csv — {len(gw_stats)} rows")
    print(f"   Columns: {list(gw_stats.columns)}")
    
    # Top performers this GW
    if "event_points" in gw_stats.columns:
        top_gw = gw_stats.nlargest(5, "event_points")[
            ["web_name", "event_points", "goals_scored", "assists", "minutes"]
        ]
        print(f"\n   Top 5 GW34 scorers:")
        print(top_gw.to_string(index=False))
except Exception as e:
    print(f"❌ GW34 stats failed: {e}")