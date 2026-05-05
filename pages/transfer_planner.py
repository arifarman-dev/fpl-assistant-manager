import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import streamlit as st
import pandas as pd
from transformer import build_player_dataframe
from llm import get_hit_analysis

st.set_page_config(page_title="Transfer Planner", page_icon="🎯")

st.title("🎯 Transfer Planner")
st.caption(
    "Plan your transfers step by step. "
    "Sell a player, pick a replacement, repeat. "
    "Budget and hit cost update in real time."
)

if "data" not in st.session_state or "context" not in st.session_state:
    st.info("👈 Please load your team in the Transfer Hub first.")
    st.stop()

data           = st.session_state["data"]
context        = st.session_state["context"]
original_squad = context["squad"].copy()
free_transfers = data["free_transfers"]
bank           = context["bank"]
bootstrap      = data["bootstrap"]
player_df      = build_player_dataframe(data["bootstrap"], data["fixtures"])

# ── session state init ────────────────────────────────────────────────────────
if "tp_transfers" not in st.session_state:
    st.session_state["tp_transfers"] = []

if "tp_selling" not in st.session_state:
    st.session_state["tp_selling"] = None

if "tp_ai" not in st.session_state:
    st.session_state["tp_ai"] = None

transfers = st.session_state["tp_transfers"]

# ── derived state ─────────────────────────────────────────────────────────────
def current_squad() -> pd.DataFrame:
    """
    Return the squad as it would look after all planned transfers.
    Sold players are replaced by bought players in the same position slot.
    """
    squad = original_squad.copy()
    for t in transfers:
        out_name = t["out"]["name"]
        in_player = t["in"]
        mask = squad["name"] == out_name
        if mask.any():
            idx = squad.index[mask][0]
            for col in ["name", "price", "form", "ep_next",
                        "fdrs", "status", "position", "team"]:
                if col in in_player.index:
                    squad.at[idx, col] = in_player[col]
            squad.at[idx, "is_captain"] = False
    return squad


def pooled_bank() -> float:
    """
    Total available budget = original bank + sum of all sell prices
    minus sum of all buy prices.
    """
    b = bank
    for t in transfers:
        b += float(t["out"]["price"]) - float(t["in"]["price"])
    return round(b, 1)


def hit_count() -> int:
    return max(0, len(transfers) - free_transfers)


def team_counts(squad: pd.DataFrame) -> dict[str, int]:
    """
    Count players per team in the given squad.
    Uses bootstrap to map player name -> team.
    """
    name_to_team = {
        p["web_name"]: next(
            (t["short_name"] for t in bootstrap["teams"]
             if t["id"] == p["team"]), "UNK"
        )
        for p in bootstrap["elements"]
    }
    counts = {}
    for _, p in squad.iterrows():
        team = name_to_team.get(p["name"], p.get("team", "UNK"))
        counts[team] = counts.get(team, 0) + 1
    return counts


def maxed_teams(squad: pd.DataFrame) -> set[str]:
    return {t for t, c in team_counts(squad).items() if c >= 3}


def available_replacements(
    position: str,
    selling_player: pd.Series,
) -> pd.DataFrame:
    """
    Find available same-position replacements given:
    - Pooled budget (all planned sales contribute)
    - 3-player team rule based on POST-transfer squad
    - Exclude players already in the squad or already being bought
    """
    squad_after = current_squad()
    squad_for_limit_check = squad_after[
        squad_after["name"] != selling_player["name"]
    ]
    maxed = maxed_teams(squad_for_limit_check)

    # Players already in the updated squad
    squad_names = set(squad_after["name"].tolist())
    # Also exclude the player being sold from the "in squad" check
    squad_names.discard(selling_player["name"])

    for t in transfers:
        squad_names.discard(t["out"]["name"])

    budget = pooled_bank() + float(selling_player["price"])

    budget = pooled_bank() + float(selling_player["price"])

    pool = player_df[
        (player_df["position"] == position) &
        (player_df["status"] == "a") &
        (player_df["minutes"] >= 900) &
        (~player_df["name"].isin(squad_names)) &
        (~player_df["team"].isin(maxed)) &
        (player_df["name"] != selling_player["name"])
    ].copy()

    # Split affordable vs over budget
    pool["affordable"] = pool["price"] <= budget
    return pool.sort_values(
        ["affordable", "ep_next"], ascending=[False, False]
    ).reset_index(drop=True)


# ── summary bar ───────────────────────────────────────────────────────────────
st.markdown("---")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Pooled budget",   f"£{pooled_bank()}m")
c2.metric("Free transfers",  free_transfers)
c3.metric("Planned",         len(transfers))
hits = hit_count()
c4.metric(
    "Hit cost",
    f"-{hits * 4} pts" if hits > 0 else "None",
    delta=f"{hits} hit(s)" if hits > 0 else "Within free transfers",
    delta_color="inverse" if hits > 0 else "normal"
)

# ── planned transfers ─────────────────────────────────────────────────────────
if transfers:
    st.markdown("---")
    st.markdown("#### Planned transfers")
    for idx, t in enumerate(transfers):
        o, i    = t["out"], t["in"]
        ep_diff = round(float(i["ep_next"]) - float(o["ep_next"]), 1)
        pr_diff = round(float(i["price"])   - float(o["price"]),   1)
        ca, cb, cc, cd = st.columns([3, 3, 2, 1])
        ca.markdown(f"🔴 **{o['name']}** £{o['price']}m · EP {o['ep_next']}")
        cb.markdown(f"🟢 **{i['name']}** £{i['price']}m · EP {i['ep_next']}")
        ep_sign = "▲" if ep_diff >= 0 else "▼"
        cc.markdown(
            f"EP {ep_sign}{abs(ep_diff):.1f} · "
            f"£{'+' if pr_diff >= 0 else ''}{pr_diff}m"
        )
        if cd.button("✕", key=f"rm_{idx}"):
            st.session_state["tp_transfers"].pop(idx)
            st.session_state["tp_selling"] = None
            st.rerun()

    if st.button("Clear all", type="secondary"):
        st.session_state["tp_transfers"]  = []
        st.session_state["tp_selling"]    = None
        st.rerun()

# ── squad view ────────────────────────────────────────────────────────────────
st.markdown("---")
selling_name = st.session_state["tp_selling"]
live_squad   = current_squad()

if selling_name is None:
    st.markdown("#### Select a player to sell")
else:
    st.markdown(
        f"#### Select a player to sell  "
        f"<span style='color:#E24B4A'>— selling **{selling_name}**</span>",
        unsafe_allow_html=True
    )

POSITIONS = ["GK", "DEF", "MID", "FWD"]

for pos in POSITIONS:
    pos_players = live_squad[live_squad["position"] == pos].sort_values(
        "pick_position"
    )
    if pos_players.empty:
        continue

    st.markdown(f"**{pos}**")
    cols = st.columns(len(pos_players))

    for col, (_, p) in zip(cols, pos_players.iterrows()):
        is_selling    = p["name"] == selling_name
        was_bought    = any(t["in"]["name"] == p["name"] for t in transfers)
        was_sold      = any(t["out"]["name"] == p["name"] for t in transfers)

        ep_col = (
            "#1D9E75" if p["ep_next"] >= 6
            else "#BA7517" if p["ep_next"] >= 4
            else "#E24B4A"
        )
        status_icon = (
            " 🔴" if p["status"] == "i"
            else " 🟡" if p["status"] == "d"
            else ""
        )

        if is_selling:
            bg     = "rgba(226,75,74,0.2)"
            border = "1.5px solid #E24B4A"
        elif was_bought:
            bg     = "rgba(29,158,117,0.15)"
            border = "1.5px solid #1D9E75"
        elif was_sold:
            bg     = "rgba(255,255,255,0.04)"
            border = "0.5px solid rgba(255,255,255,0.1)"
        else:
            bg     = "rgba(255,255,255,0.03)"
            border = "0.5px solid rgba(255,255,255,0.1)"

        tag = ""
        if is_selling:
            tag = "<p style='margin:1px 0;font-size:9px;color:#E24B4A'>SELECTING...</p>"
        elif was_bought:
            tag = "<p style='margin:1px 0;font-size:9px;color:#1D9E75'>NEW</p>"

        with col:
            st.markdown(
                f'<div style="background:{bg};border:{border};'
                f'border-radius:8px;padding:8px 4px;text-align:center">'
                f'<p style="margin:0;font-size:11px;font-weight:600;'
                f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
                f'{p["name"]}{status_icon}</p>'
                f'<p style="margin:1px 0;font-size:10px;'
                f'color:rgba(255,255,255,0.45)">£{p["price"]}m</p>'
                f'<p style="margin:0;font-size:11px;font-weight:600;'
                f'color:{ep_col}">EP {p["ep_next"]}</p>'
                f'{tag}'
                f'</div>',
                unsafe_allow_html=True
            )

            # Only show sell button if not already sold/being sold
            if not was_sold and not is_selling:
                if st.button("Sell", key=f"sell_{p['name']}",
                             use_container_width=True):
                    st.session_state["tp_selling"] = p["name"]
                    st.rerun()
            elif is_selling:
                if st.button("Cancel", key=f"cancel_{p['name']}",
                             use_container_width=True):
                    st.session_state["tp_selling"] = None
                    st.rerun()

# ── replacement picker ────────────────────────────────────────────────────────
if selling_name:
    # Find the player being sold from original squad
    selling_rows = original_squad[original_squad["name"] == selling_name]
    if selling_rows.empty:
        # Might have been a previously bought player
        for t in transfers:
            if t["in"]["name"] == selling_name:
                selling_player = t["in"]
                break
    else:
        selling_player = selling_rows.iloc[0]

    out_pos    = selling_player["position"]
    budget     = round(pooled_bank() + float(selling_player["price"]), 1)

    st.markdown("---")
    st.markdown(
        f"#### Replacements for **{selling_name}** "
        f"({out_pos} · £{selling_player['price']}m · EP {selling_player['ep_next']})"
    )
    st.caption(
        f"Budget: £{budget}m (bank + all sales so far) · "
        f"Position: {out_pos} only · "
        f"Teams at 3-player limit are excluded automatically"
    )

    pool = available_replacements(out_pos, selling_player)

    if pool.empty:
        st.warning(
            f"No available {out_pos} players found. "
            f"You may be at the 3-player limit for all teams with good options."
        )
    else:
        affordable   = pool[pool["affordable"]].head(12)
        over_budget  = pool[~pool["affordable"]].head(6)

        if not affordable.empty:
            st.markdown("**Within budget:**")
            n = min(4, len(affordable))
            rows_needed = -(-len(affordable) // n)

            for row_i in range(rows_needed):
                row_players = affordable.iloc[row_i * n: row_i * n + n]
                cols = st.columns(n)
                for col, (_, p) in zip(cols, row_players.iterrows()):
                    ep_col = (
                        "#1D9E75" if p["ep_next"] >= 6
                        else "#BA7517" if p["ep_next"] >= 4
                        else "#E24B4A"
                    )
                    with col:
                        st.markdown(
                            f'<div style="background:rgba(29,158,117,0.08);'
                            f'border:0.5px solid rgba(29,158,117,0.3);'
                            f'border-radius:8px;padding:8px 4px;'
                            f'text-align:center">'
                            f'<p style="margin:0;font-size:11px;font-weight:600;'
                            f'white-space:nowrap;overflow:hidden;'
                            f'text-overflow:ellipsis">{p["name"]}</p>'
                            f'<p style="margin:1px 0;font-size:10px;'
                            f'color:rgba(255,255,255,0.45)">'
                            f'£{p["price"]}m · {p["team"]}</p>'
                            f'<p style="margin:0;font-size:11px;font-weight:600;'
                            f'color:{ep_col}">EP {p["ep_next"]}</p>'
                            f'<p style="margin:1px 0;font-size:9px;'
                            f'color:rgba(255,255,255,0.3)">'
                            f'{str(p["fdrs"])[:28]}</p>'
                            f'</div>',
                            unsafe_allow_html=True
                        )
                        if st.button(
                            "Buy", key=f"buy_{p['name']}",
                            use_container_width=True
                        ):
                            st.session_state["tp_transfers"].append({
                                "out": selling_player,
                                "in":  p,
                            })
                            st.session_state["tp_selling"] = None
                            st.rerun()

        if not over_budget.empty:
            with st.expander(
                f"💸 {len(over_budget)} over-budget options "
                f"(sell another player to unlock funds)"
            ):
                for _, p in over_budget.iterrows():
                    shortfall = round(float(p["price"]) - budget, 1)
                    st.markdown(
                        f"**{p['name']}** ({p['team']}) · "
                        f"£{p['price']}m · EP {p['ep_next']} · "
                        f"*£{shortfall}m short — sell another player first*"
                    )

# ── final verdict ─────────────────────────────────────────────────────────────
if transfers:
    st.markdown("---")
    st.subheader("📊 Plan summary")

    # Current squad total EP (before transfers)
    current_ep = original_squad["ep_next"].sum()
    
    # Post-transfer squad total EP
    post_squad  = current_squad()
    post_ep     = post_squad["ep_next"].sum()
    
    # Hit cost
    hit_cost    = hit_count() * 4
    
    # Net expected points with hit factored in
    net_post_ep = round(post_ep - hit_cost, 1)
    ep_gain     = round(post_ep - current_ep, 1)
    
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric(
        "Current squad EP",
        f"{current_ep:.1f}"
    )
    m2.metric(
        "Post-transfer EP",
        f"{post_ep:.1f}",
        delta=f"{ep_gain:+.1f}"
    )
    m3.metric(
        "Hit cost",
        f"-{hit_cost} pts" if hit_cost > 0 else "Free"
    )
    m4.metric(
        "Net EP after hit",
        f"{net_post_ep:.1f}",
        delta=f"{round(net_post_ep - current_ep, 1):+.1f}",
        delta_color="normal"
    )
    m5.metric(
        "Bank after",
        f"£{pooled_bank()}m"
    )

    if hit_cost == 0:
        st.success(
            f"✅ Within free transfers. "
            f"Squad EP increases from {current_ep:.1f} to {post_ep:.1f} "
            f"(+{ep_gain:.1f} pts)."
        )
    elif net_post_ep > current_ep:
        st.success(
            f"✅ Worth the hit. Squad EP goes from {current_ep:.1f} to "
            f"{post_ep:.1f} (+{ep_gain:.1f}), net {net_post_ep:.1f} "
            f"after -{hit_cost} pt cost."
        )
    elif net_post_ep == current_ep:
        st.warning(
            f"⚠️ Break even this GW. Squad EP {current_ep:.1f} → "
            f"{net_post_ep:.1f} net. Only do this if forced by injury."
        )
    else:
        loss = round(current_ep - net_post_ep, 1)
        st.error(
            f"❌ Not worth it. You lose {loss:.1f} expected pts net "
            f"({current_ep:.1f} → {net_post_ep:.1f}). Roll the transfer."
        )

    if hit_cost > 0 and ep_gain > 0:
        breakeven = round(hit_cost / (ep_gain / len(transfers)), 1)
        st.caption(
            f"Breakeven: ~{breakeven} GWs to recover "
            f"the -{hit_cost} pt cost at current EP rates."
        )

    st.markdown("---")
    if st.button(
        "🤖 Get AI verdict on this plan",
        type="primary",
        use_container_width=True
    ):
        with st.spinner("Analysing..."):
            analyses = []
            for t in transfers:
                a = get_hit_analysis(
                    player_out=t["out"],
                    player_in=t["in"],
                    context=context
                )
                analyses.append(
                    f"**{t['out']['name']} → {t['in']['name']}**\n\n{a}"
                )
            st.session_state["tp_ai"] = "\n\n---\n\n".join(analyses)

    if "tp_ai" in st.session_state:
        st.markdown(st.session_state["tp_ai"])