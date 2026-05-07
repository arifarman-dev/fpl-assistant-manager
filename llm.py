#llm.py
import requests
import pandas as pd
from config import OPENROUTER_API_KEY, MODEL
from config import OPENROUTER_API_KEY, MODEL, MODEL_FAST

SYSTEM_PROMPT = """You are an expert Fantasy Premier League (FPL) assistant manager.

Key definitions:
- Form: average FPL points per match over last 30 days. Higher is better.
- ep_next: FPL's predicted points for the next gameweek.
- FDR: Fixture Difficulty Rating 1-5. 1-2 = easy, 3 = moderate, 4-5 = hard.
- Win%: bookmaker-implied probability that the player's team wins their next match. Higher = better attacking/clean sheet potential.
- O2.5%: implied probability of over 2.5 goals in the match. High = good for attackers, bad for defenders/GKs.
- Status: "a" = available, "d" = doubtful, "i" = injured, "s" = suspended.
- Rolling a transfer: choosing NOT to transfer this week, banking the free transfer
  for next week (max 2 banked).
- Taking a hit: making an extra transfer beyond your free allocation, costing 4 points.
  Only worth it if the player gained is expected to outscore the replacement by 4+ points.

CRITICAL GROUNDING RULES — you must follow these without exception:
- Only reference players, stats, and fixtures explicitly provided in the data below.
- Do not invent statistics, ownership percentages, or fixture details not in the prompt.
- Do not reference real-world match results, manager decisions, or news 
  unless it appears in the 'news' field of the data provided.
- If you are uncertain about a claim, do not make it.
- Every recommendation must cite a specific number from the data provided.

CRITICAL TRANSFER RULES — these are hard FPL game rules, never break them:
- A goalkeeper can ONLY be replaced by another goalkeeper. Never suggest GK → outfield or outfield → GK.
- A defender can ONLY be replaced by another defender.
- A midfielder can ONLY be replaced by another midfielder.
- A forward can ONLY be replaced by another forward.
- Candidates are already filtered by position — only recommend players from the matching position section.
- Evaluate the full 5-GW FDR run when comparing candidates. A single easy fixture followed by 4 hard ones is NOT a good transfer target. Prioritise players with a good run across GWs 2-5, not just GW1.

CRITICAL CAPTAIN RULES:
- The captain must be a player already in the squad (not a transfer target).
- When describing a player's fixture, state their OPPONENT — not their own team name.
  Example: "Haaland (MCI) faces WHU" — NOT "Haaland plays Manchester City".
- A DGW means the player's team plays TWICE in that gameweek, against two different opponents.

Your responsibilities:
1. Identify urgent problems in the squad (injuries, poor form, bad fixtures).
2. Compare the manager's players against available candidates across 
   the next 5 gameweeks — not just the immediate one.
3. Recommend whether to use free transfers, roll them, or take a hit.
4. Suggest captain pick from the current squad.
5. Only recommend players from the candidate list provided, matched by position.
6. Be direct and confident. Reference specific numbers from the data."""


def format_squad_for_prompt(squad, bank: float) -> str:
    """Format the squad DataFrame into a readable prompt string."""
    lines = [
        f"CURRENT SQUAD (Bank: £{bank}m)",
        f"{'Name':<18} {'Pos':<5} {'£':<6} {'Form':<6} {'EP':<6} "
        f"{'xG/90':<7} {'xA/90':<7} {'Chance%':<9} {'Fixtures (GW vs OPP(FDR))':<45} {'Status'} {'News'}",
        "-" * 125
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
            f"{chance:<9} {p['fdrs']:<45} {p['status']}  {news}"
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
            f"  {'Name':<18} {'Team':<6} {'£':<6} {'Form':<6} {'EP Next':<9} "
            f"{'Fixtures (GW vs OPP(FDR))':<40} {'Win%':<6} {'O2.5%':<7} {'Score'}"
        )
        lines.append("  " + "-" * 105)
        for _, p in df.iterrows():
            win_prob = f"{p['win_prob']:.0f}%" if pd.notna(p.get('win_prob')) else "n/a"
            over25 = f"{p['over25_prob']:.0f}%" if pd.notna(p.get('over25_prob')) else "n/a"
            lines.append(
                f"  {p['name']:<18} {p['team']:<6} £{p['price']:<5.1f} "
                f"{p['form']:<6} {p['ep_next']:<9} {p['fdrs']:<40} "
                f"{win_prob:<6} {over25:<7} {p['score']:.2f}"
            )
    return "\n".join(lines)


def format_fixture_comparison(context: dict) -> str:
    """
    Compare your weakest players directly against top candidates
    across the next 5 gameweeks. Helps LLM reason about rolling transfers.
    Only shows same-position candidates — cross-position transfers are not allowed.
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

    lines = ["FIXTURE COMPARISON — Weak squad players vs same-position candidates:"]
    lines.append("(Transfers are position-locked: only same-position swaps are valid)\n")

    for _, player in weak.iterrows():
        pos = player["position"]
        lines.append(f"YOUR {pos}:    {player['name']:<18} "
                     f"£{player['price']} | Form: {player['form']} | "
                     f"EP: {player['ep_next']} | FDR: {player['fdrs']} "
                     f"| Status: {player['status']}")

        if pos in candidates and not candidates[pos].empty:
            top3 = candidates[pos].head(3)
            for _, cand in top3.iterrows():
                lines.append(f"  {pos} CANDIDATE: {cand['name']:<18} "
                             f"£{cand['price']} | Form: {cand['form']} | "
                             f"EP: {cand['ep_next']} | FDR: {cand['fdrs']}")
        else:
            lines.append(f"  No {pos} candidates available within budget.")
        lines.append("")

    return "\n".join(lines)

def format_season_plan_for_prompt(season_plan: dict, team_map: dict) -> str:
    lines = ["SEASON FIXTURE PLAN (remaining GWs with DGW/BGW only):"]

    bgw_dgw = season_plan["bgw_dgw"]
    squad_analysis = season_plan["squad_gw_analysis"]
    dgw_targets = season_plan["dgw_targets"]
    chip_windows = season_plan["chip_windows"]

    for gw in sorted(bgw_dgw.keys()):
        info = bgw_dgw[gw]

        # Only include GWs that have something noteworthy
        if not info["doubles"] and not info["blanks"]:
            continue

        squad_info = squad_analysis.get(gw, {})
        flags = []

        if info["doubles"]:
            double_teams = [team_map.get(t, str(t)) for t in info["doubles"]]
            flags.append(f"DGW: {', '.join(double_teams)}")
        if info["blanks"]:
            blank_teams = [team_map.get(t, str(t)) for t in info["blanks"]]
            flags.append(f"BGW: {', '.join(blank_teams)}")

        lines.append(f"GW{gw}: {' | '.join(flags)}")

        if squad_info.get("doubles"):
            lines.append(f"  Your doublers: {', '.join(squad_info['doubles'])}")
        if squad_info.get("blanks"):
            lines.append(f"  Your blankers: {', '.join(squad_info['blanks'])}")

        if gw in dgw_targets and dgw_targets[gw]:
            top3 = dgw_targets[gw][:3]
            target_str = ", ".join(
                f"{t['name']} ({t['team']}, £{t['price']}m)"
                for t in top3
            )
            lines.append(f"  Targets: {target_str}")

    if chip_windows:
        lines.append("\nCHIP WINDOWS:")
        for c in chip_windows:
            lines.append(f"  GW{c['gw']}: {c['chip']} — {c['reason']}")

    return "\n".join(lines)

def build_user_prompt(context: dict, free_transfers: int = 1) -> str:
    squad_text = format_squad_for_prompt(context["squad"], context["bank"])
    candidates_text = format_candidates_for_prompt(context["candidates"])
    comparison_text = format_fixture_comparison(context)

    chip_status = context.get("chip_status", {})
    available_chips = chip_status.get("available", [])
    used_chips = chip_status.get("used", [])

    chips_text = (
        f"Chips AVAILABLE (not yet used): "
        f"{', '.join(available_chips) if available_chips else 'NONE — all chips used'}\n"
        f"Chips ALREADY USED this season: "
        f"{', '.join(used_chips) if used_chips else 'None used yet'}"
    )

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
Bank: £{context['bank']}m | Free transfers: {free_transfers}
{chips_text}
Urgent: {injured_count} injured, {doubtful_count} doubtful in squad.

IMPORTANT RULES:
- Maximum 3 players from the same club.
- Transfers are POSITION-LOCKED: GK out → GK in only. DEF out → DEF in only. MID out → MID in only. FWD out → FWD in only. Never suggest cross-position transfers.
- Only recommend players from the TRANSFER CANDIDATES section, matched to the correct position block.
- When choosing between candidates, evaluate the FULL 5-GW fixture run in the FDR column — not just the next gameweek. A player with FDR 1 this week but 5/5/5 after is a liability. Prefer players with consistently low FDR across GWs 2-5.
- Only recommend chips listed as AVAILABLE. If none available, skip chip section entirely.
- Do NOT include a Starting XI or lineup selection section — this is handled separately.
- Keep the response concise. No unnecessary closing remarks or motivational comments.

{squad_text}

{candidates_text}

{comparison_text}

{season_text}

Provide exactly these 5 sections. Start each section on a new line with its number and title, then a blank line, then the content, then "---" on its own line.

1. Squad problems
One bullet per player with an issue.

2. Transfer strategy
One short paragraph.

3. Specific transfers
One bullet per transfer: PLAYER OUT (POS) → PLAYER IN (POS) — one sentence justification with stats.

4. Chip strategy
Only mention chips listed as AVAILABLE. If none, write: No chips available this season.

5. Captain pick
Name, EP, and their next opponent from the FDR column.
---"""


def get_recommendation(context: dict, free_transfers: int = 1) -> str:
    user_prompt = build_user_prompt(context, free_transfers)

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": 3000
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

def get_hit_analysis(
    player_out: pd.Series,
    player_in: pd.Series,
    context: dict,
    is_free_transfer: bool = True
) -> str:
    transfer_type = (
        "FREE TRANSFER (no point cost)"
        if is_free_transfer
        else "HIT TRANSFER (costs -4 points)"
    )

    out_name = str(player_out['name'])
    in_name  = str(player_in['name'])

    prompt = f"""You are an FPL analyst. Give exactly 3 bullet points analysing this transfer.

Transfer type: {transfer_type}
Selling: {out_name} | EP next GW: {player_out['ep_next']} | Form: {player_out['form']} | Fixtures: {player_out['fdrs']}
Buying:  {in_name} | EP next GW: {player_in['ep_next']} | Form: {player_in['form']} | Fixtures: {player_in['fdrs']}

Rules:
- Only mention {out_name} and {in_name} by name, no other players.
- Do not discuss budget or cost.
- Base all fixture comments on the fixture data above only.

Bullet points must be exactly:
- EP gain this GW: [write the number {round(float(player_in['ep_next']) - float(player_out['ep_next']), 1):+.1f}]
- Breakeven: {"N/A — free transfer" if is_free_transfer else f"approximately {round(4 / max(float(player_in['ep_next']) - float(player_out['ep_next']), 0.1), 1)} GWs"}
- Biggest risk of bringing in {in_name}: [one sentence about their upcoming fixtures or form]"""

    payload = {
        "model": MODEL_FAST,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 200
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
    return response.json()["choices"][0]["message"]["content"]

def get_differential_insight(diffs: pd.DataFrame, current_gw: int) -> str:
    """
    Ask the LLM to give a brief, punchy insight on the top differentials.
    No stats dumping — just the most interesting findings.
    """
    # Format top 10 for the prompt
    top = diffs.head(10)
    players_text = "\n".join(
        f"- {row['name']} ({row['team']}, {row['position']}, "
        f"£{row['price']}m) | Form: {row['form']} | "
        f"EP Next: {row['ep_next']} | Owned: {row['selected_pct']}% | "
        f"Fixtures: {row['fdrs']}"
        for _, row in top.iterrows()
    )

    prompt = f"""You are analysing FPL differential picks for GW{current_gw}.
These are high-form, low-ownership players most managers are missing.

{players_text}

Give a punchy 2-paragraph maximum insight:
1. The single most compelling differential and exactly why (specific numbers)
2. One to be cautious about despite good numbers

Be direct and concise. Maximum 150 words total. 
Write like a confident FPL analyst giving quick advice before a deadline."""

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 800
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
    return response.json()["choices"][0]["message"]["content"]