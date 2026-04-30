import requests
import pandas as pd
from config import OPENROUTER_API_KEY, MODEL


SYSTEM_PROMPT = """You are an expert Fantasy Premier League (FPL) transfer recommendation assistant.

Key definitions:
- Form: a player's average FPL points per match over the last 30 days. Higher is better.
- ep_next: FPL's own model prediction for a player's points in the next gameweek. Higher is better.
- Fixture Difficulty Rating (FDR): rated 1-5 per gameweek. 1-2 = easy, 3 = moderate, 4-5 = difficult.
- Status "a" = available, "d" = doubtful, "i" = injured, "s" = suspended.
- Price is in millions (£). The manager cannot exceed their available budget for a transfer.
- A transfer costs one free transfer. Taking an additional transfer costs 4 points.

Your job:
- Analyse the manager's current squad critically — identify the weakest player(s) based on form, ep_next, injury status, and upcoming fixtures.
- Recommend the single best transfer: one player to sell, one player to bring in.
- Justify your recommendation using the specific numbers provided.
- If a player is injured or doubtful, flag this prominently.
- Only recommend players from the candidate list provided. Do not invent or suggest players outside this list.
- Be concise, direct, and confident. This manager is experienced and wants actionable advice."""


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


def build_user_prompt(context: dict) -> str:
    """Build the full user prompt from the transformed context."""
    squad_text = format_squad_for_prompt(context["squad"], context["bank"])
    candidates_text = format_candidates_for_prompt(context["candidates"])

    return f"""Please analyse my FPL team and recommend the best transfer for the upcoming gameweek.

Manager: {context['manager']}
Team: {context['team_name']}

{squad_text}

{candidates_text}

Please provide:
1. The weakest player(s) in my squad and why
2. Your single recommended transfer (who to sell, who to bring in)
3. A clear justification referencing the specific stats above
4. Any other urgent issues I should be aware of (injuries, blanks, etc.)"""


def get_recommendation(context: dict) -> str:
    """
    Send the squad and candidates to the LLM and return a transfer recommendation.
    """
    user_prompt = build_user_prompt(context)

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