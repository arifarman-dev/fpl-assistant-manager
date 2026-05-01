import requests
import pandas as pd
from config import OPENROUTER_API_KEY, MODEL


SYSTEM_PROMPT = """You are an expert Fantasy Premier League (FPL) assistant manager.

Key definitions:
- Form: average FPL points per match over last 30 days. Higher is better.
- ep_next: FPL's predicted points for the next gameweek.
- FDR: Fixture Difficulty Rating 1-5. 1-2 = easy, 3 = moderate, 4-5 = hard.
- Status: "a" = available, "d" = doubtful, "i" = injured, "s" = suspended.
- Rolling a transfer: choosing NOT to transfer this week, banking the free transfer 
  for next week (max 2 banked). Worth doing if no urgent need this week but 
  great targets exist for upcoming gameweeks.
- Taking a hit: making an extra transfer beyond your free allocation, costing 4 points.
  Only worth it if the player gained is expected to outscore the replacement by 4+ points.

Your responsibilities:
1. Identify urgent problems in the squad (injuries, poor form, bad fixtures).
2. Compare the manager's players against available candidates across the NEXT 5 GAMEWEEKS,
   not just the immediate one. Flag if rolling a transfer makes more sense than acting now.
3. Recommend whether to: use free transfer(s) now, roll transfer(s), or take a hit.
4. Suggest captain pick from the current squad.
5. Only recommend players from the candidate list provided.
6. Be direct and confident. Reference specific numbers."""


def format_squad_for_prompt(squad, bank: float) -> str:
    """Format the squad DataFrame into a readable prompt string."""
    lines = [
        f"CURRENT SQUAD (Bank: £{bank}m)",
        f"{'Name':<18} {'Pos':<5} {'£':<6} {'Form':<6} {'EP':<6} "
        f"{'xG/90':<7} {'xA/90':<7} {'Chance%':<9} {'FDR':<20} {'Status'} {'News'}",
        "-" * 110
    ]
    for _, p in squad.iterrows():
        captain = " ©" if p.get("is_captain") else ""
        raw_chance = p.get("chance_of_playing_next_round")
        chance = f"{raw_chance:.0f}%" if pd.notna(raw_chance) else "100%" \
            if pd.notna(p.get("chance_of_playing_next_round")) else "100%"
        xg = f"{p['expected_goals_per_90']:.2f}" \
            if pd.notna(p.get("expected_goals_per_90")) else "n/a"
        xa = f"{p['expected_assists_per_90']:.2f}" \
            if pd.notna(p.get("expected_assists_per_90")) else "n/a"
        news = p.get("news", "") or ""

        lines.append(
            f"{p['name'] + captain:<18} {p['position']:<5} £{p['price']:<5.1f} "
            f"{p['form']:<6} {p['ep_next']:<6} {xg:<7} {xa:<7} "
            f"{chance:<9} {p['fdrs']:<20} {p['status']}  {news}"
        )
    return "\n".join(lines)


def format_candidates_for_prompt(candidates: dict) -> str:
    """Format transfer candidates into a readable prompt string."""
    lines = ["TRANSFER CANDIDATES (available players only, ranked by score):"]
    for position, df in candidates.items():
        if df.empty:
            continue
        lines.append(f"\n{position}:")
        lines.append(
            f"  {'Name':<18} {'Team':<6} {'£':<6} {'Form':<6} {'EP Next':<9} {'FDR (next 5 GWs)':<25} {'Score'}"
        )
        lines.append("  " + "-" * 80)
        for _, p in df.iterrows():
            lines.append(
                f"  {p['name']:<18} {p['team']:<6} £{p['price']:<5.1f} "
                f"{p['form']:<6} {p['ep_next']:<9} {p['fdrs']:<25} {p['score']:.2f}"
            )
    return "\n".join(lines)


def format_fixture_comparison(context: dict) -> str:
    """
    Compare your weakest players directly against top candidates
    across the next 5 gameweeks. Helps LLM reason about rolling transfers.
    """
    squad = context["squad"]
    candidates = context["candidates"]

    # Find weakest starters — low ep_next or injured/doubtful
    weak = squad[
        (squad["ep_next"] < 4) |
        (squad["status"].isin(["i", "d"]))
    ][["name", "position", "price", "form", "ep_next", "fdrs", "status"]]

    if weak.empty:
        return ""

    lines = ["FIXTURE COMPARISON — Weak squad players vs top candidates:"]
    lines.append("(Use this to judge whether to act now or roll transfer)\n")

    for _, player in weak.iterrows():
        pos = player["position"]
        lines.append(f"YOUR PLAYER:  {player['name']:<18} {pos} "
                     f"£{player['price']} | Form: {player['form']} | "
                     f"EP: {player['ep_next']} | FDR: {player['fdrs']} "
                     f"| Status: {player['status']}")

        if pos in candidates and not candidates[pos].empty:
            top3 = candidates[pos].head(3)
            for _, cand in top3.iterrows():
                lines.append(f"  CANDIDATE:  {cand['name']:<18} {pos} "
                             f"£{cand['price']} | Form: {cand['form']} | "
                             f"EP: {cand['ep_next']} | FDR: {cand['fdrs']}")
        lines.append("")

    return "\n".join(lines)

def format_season_plan_for_prompt(season_plan: dict, team_map: dict) -> str:
    """Format the season plan into a readable section for the LLM prompt."""
    lines = ["SEASON FIXTURE PLAN — Remaining gameweeks:"]
    lines.append("(DGW = Double Gameweek, BGW = Blank Gameweek)\n")

    bgw_dgw = season_plan["bgw_dgw"]
    squad_analysis = season_plan["squad_gw_analysis"]
    dgw_targets = season_plan["dgw_targets"]
    chip_windows = season_plan["chip_windows"]

    for gw in sorted(bgw_dgw.keys()):
        info = bgw_dgw[gw]
        squad_info = squad_analysis.get(gw, {})

        flags = []
        if info["doubles"]:
            double_teams = [team_map.get(t, str(t)) for t in info["doubles"]]
            flags.append(f"DGW: {', '.join(double_teams)}")
        if info["blanks"]:
            blank_teams = [team_map.get(t, str(t)) for t in info["blanks"]]
            flags.append(f"BGW: {', '.join(blank_teams)}")

        flag_str = " | ".join(flags) if flags else "Normal"
        lines.append(f"GW{gw}: {flag_str}")

        if squad_info.get("doubles"):
            lines.append(f"  YOUR players doubling: "
                        f"{', '.join(squad_info['doubles'])}")
        if squad_info.get("blanks"):
            lines.append(f"  YOUR players blanking: "
                        f"{', '.join(squad_info['blanks'])}")

        if gw in dgw_targets and dgw_targets[gw]:
            top_targets = dgw_targets[gw][:3]
            target_str = ", ".join(
                f"{t['name']} ({t['team']}, £{t['price']}m, "
                f"form {t['form']})"
                for t in top_targets
            )
            lines.append(f"  DGW targets to consider: {target_str}")

    if chip_windows:
        lines.append("\nCHIP DEPLOYMENT SUGGESTIONS:")
        for c in chip_windows:
            lines.append(f"  GW{c['gw']}: {c['chip']} — {c['reason']}")

    return "\n".join(lines)

def build_user_prompt(context: dict, free_transfers: int = 1) -> str:
    squad_text = format_squad_for_prompt(context["squad"], context["bank"])
    candidates_text = format_candidates_for_prompt(context["candidates"])
    comparison_text = format_fixture_comparison(context)

    chips = context.get("active_chip", "None")
    injured_count = len(context["squad"][context["squad"]["status"] == "i"])
    doubtful_count = len(context["squad"][context["squad"]["status"] == "d"])

    if context.get("season_plan"):
        season_text = format_season_plan_for_prompt(
            context["season_plan"],
            context["season_plan"]["team_map"]
        )
    else:
        season_text = ""

    return f"""Analyse my FPL team and provide a complete gameweek strategy.

Manager: {context['manager']} | Team: {context['team_name']}
Bank: £{context['bank']}m | Free transfers: {free_transfers} | Active chip: {chips}
Urgent: {injured_count} injured, {doubtful_count} doubtful in squad.

{squad_text}

{candidates_text}

{comparison_text}

{season_text}

Please provide:
1. Squad problems — injuries, poor form, bad upcoming fixtures
2. Transfer strategy considering DGW/BGW gameweeks ahead — use transfers now, roll, or take a hit?
3. Specific transfers — prioritise DGW assets if timing is right, with full justification
4. Chip strategy — which chips to use and in which gameweeks
5. Captain recommendation for this gameweek with reasoning
6. Anything else I should know before the deadline"""


def get_recommendation(context: dict, free_transfers: int = 1) -> str:
    user_prompt = build_user_prompt(context, free_transfers)

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": 8000
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
    }

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        json=payload,
        headers=headers,
        timeout=60
    )
    response.raise_for_status()
    data = response.json()

    return data["choices"][0]["message"]["content"]