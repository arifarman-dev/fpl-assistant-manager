import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fetcher import fetch_all
from transformer import build_recommendation_context

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.abspath(os.path.dirname(__file__)), 'pages'))

import pandas as pd
from collections import defaultdict


def detect_blank_and_double_gameweeks(fixtures: list) -> dict:
    """
    Scan all remaining fixtures and identify:
    - Double gameweeks: team plays twice in one GW
    - Blank gameweeks: team has no fixture in a GW
    Returns a dict with GW -> {doubles: [...], blanks: [...]}
    """
    # Count fixtures per team per GW
    gw_team_count = defaultdict(lambda: defaultdict(int))
    all_teams = set()

    for f in fixtures:
        if f["event"] is None:
            continue
        gw = f["event"]
        gw_team_count[gw][f["team_h"]] += 1
        gw_team_count[gw][f["team_a"]] += 1
        all_teams.add(f["team_h"])
        all_teams.add(f["team_a"])

    remaining_gws = [gw for gw in gw_team_count if not all(
        f["finished"] for f in fixtures if f["event"] == gw
    )]

    analysis = {}
    for gw in sorted(remaining_gws):
        teams_this_gw = gw_team_count[gw]
        doubles = [team for team, count in teams_this_gw.items() if count >= 2]
        blanks = [team for team in all_teams if team not in teams_this_gw]

        analysis[gw] = {
            "doubles": doubles,
            "blanks": blanks,
            "all_teams_playing": list(teams_this_gw.keys())
        }

    return analysis


def get_team_fixture_run(
    team_id: int,
    fixtures: list,
    current_gw: int,
    n_gws: int = 8
) -> list[dict]:
    """
    Get a team's full fixture run for the next N gameweeks.
    Includes home/away, opponent, FDR, and DGW/BGW flags.
    """
    upcoming = [
        f for f in fixtures
        if f["event"] and f["event"] > current_gw
        and not f["finished"]
        and (f["team_h"] == team_id or f["team_a"] == team_id)
    ]
    upcoming = sorted(upcoming, key=lambda x: x["event"])

    run = []
    for f in upcoming[:n_gws]:
        is_home = f["team_h"] == team_id
        run.append({
            "gw": f["event"],
            "opponent": f["team_a"] if is_home else f["team_h"],
            "home": is_home,
            "fdr": f["team_h_difficulty"] if is_home else f["team_a_difficulty"],
        })
    return run


def build_season_plan(
    bootstrap: dict,
    fixtures: list,
    squad: pd.DataFrame,
    candidates: dict,
    current_gw: int
) -> dict:
    """
    Build a season-long fixture plan that:
    1. Identifies DGW/BGW for remaining gameweeks
    2. Flags which of YOUR players are affected
    3. Identifies premium targets for DGW gameweeks
    4. Suggests chip deployment windows
    """
    team_map = {t["id"]: t["short_name"] for t in bootstrap["teams"]}
    bgw_dgw = detect_blank_and_double_gameweeks(fixtures)

    # Map squad players to their team IDs
    player_team_map = {
        p["id"]: p["team"]
        for p in bootstrap["elements"]
    }
    id_to_name = {p["id"]: p["web_name"] for p in bootstrap["elements"]}

    # Check which squad players are in DGW/BGW teams
    squad_team_ids = {}
    for _, p in squad.iterrows():
        match = [
            el for el in bootstrap["elements"]
            if el["web_name"] == p["name"]
        ]
        if match:
            squad_team_ids[p["name"]] = match[0]["team"]

    squad_gw_analysis = {}
    for gw, info in bgw_dgw.items():
        affected = {
            "doubles": [],
            "blanks": [],
            "playing": []
        }
        for player_name, team_id in squad_team_ids.items():
            if team_id in info["doubles"]:
                affected["doubles"].append(player_name)
            elif team_id in info["blanks"]:
                affected["blanks"].append(player_name)
            elif team_id in info["all_teams_playing"]:
                affected["playing"].append(player_name)

        squad_gw_analysis[gw] = affected

    # Find best DGW targets from candidate pool
    dgw_targets = {}
    for gw, info in bgw_dgw.items():
        if not info["doubles"]:
            continue
        dgw_targets[gw] = []
        for pos, df in candidates.items():
            for _, p in df.iterrows():
                # Find player's team
                match = [
                    el for el in bootstrap["elements"]
                    if el["web_name"] == p["name"]
                ]
                if match and match[0]["team"] in info["doubles"]:
                    dgw_targets[gw].append({
                        "name": p["name"],
                        "position": pos,
                        "price": p["price"],
                        "form": p["form"],
                        "ep_next": p["ep_next"],
                        "team": team_map.get(match[0]["team"], "UNK")
                    })

    # Chip recommendation logic
    chip_windows = suggest_chip_windows(bgw_dgw, dgw_targets, current_gw)

    return {
        "bgw_dgw": bgw_dgw,
        "squad_gw_analysis": squad_gw_analysis,
        "dgw_targets": dgw_targets,
        "chip_windows": chip_windows,
        "team_map": team_map
    }


def suggest_chip_windows(
    bgw_dgw: dict,
    dgw_targets: dict,
    current_gw: int
) -> list[dict]:
    """
    Suggest optimal chip deployment based on DGW/BGW patterns.
    Logic:
    - Triple Captain: best in a DGW for a premium captain option
    - Bench Boost: best in a DGW when you have 15 players all playing
    - Free Hit: best in a BGW to avoid blank players
    - Wildcard: best before a run of good fixtures or before a DGW
    """
    suggestions = []

    for gw, info in sorted(bgw_dgw.items()):
        if gw <= current_gw:
            continue

        n_doubles = len(info["doubles"])
        n_blanks = len(info["blanks"])
        n_targets = len(dgw_targets.get(gw, []))

        if n_doubles >= 6 and n_targets >= 4:
            suggestions.append({
                "gw": gw,
                "chip": "Triple Captain / Bench Boost",
                "reason": f"{n_doubles} teams have a double — "
                          f"{n_targets} premium targets available",
                "strength": "strong"
            })
        elif n_blanks >= 8:
            suggestions.append({
                "gw": gw,
                "chip": "Free Hit",
                "reason": f"{n_blanks} teams blank — "
                          f"Free Hit avoids fielding blank players",
                "strength": "strong"
            })
        elif n_doubles >= 3:
            suggestions.append({
                "gw": gw,
                "chip": "Triple Captain",
                "reason": f"{n_doubles} teams double — "
                          f"good TC opportunity if you own a doubling premium",
                "strength": "moderate"
            })

    return suggestions