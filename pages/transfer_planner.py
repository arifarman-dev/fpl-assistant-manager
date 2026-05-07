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
    "Sell a player, pick a replacement — including over-budget targets. "
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
    b = bank
    for t in transfers:
        b += float(t["out"]["price"]) - float(t["in"]["price"])
    return round(b, 1)


def hit_count() -> int:
    return max(0, len(transfers) - free_transfers)


def team_counts(squad: pd.DataFrame) -> dict[str, int]:
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
    show_over_budget: bool = True
) -> pd.DataFrame:
    """
    Find available same-position replacements.
    Always shows over-budget options — budget column tells user
    how much extra they need to free up.
    """
    squad_after = current_squad()
    squad_for_limit_check = squad_after[
        squad_after["name"] != selling_player["name"]
    ]
    maxed = maxed_teams(squad_for_limit_check)

    squad_names = set(squad_after["name"].tolist())
    squad_names.discard(selling_player["name"])
    for t in transfers:
        squad_names.discard(t["out"]["name"])

    budget = pooled_bank() + float(selling_player["price"])

    pool = player_df[
        (player_df["position"] == position) &
        (player_df["status"] == "a") &
        (player_df["minutes"] >= 900) &
        (~player_df["name"].isin(squad_names)) &
        (~player_df["team"].isin(maxed)) &
        (player_df["name"] != selling_player["name"])
    ].copy()

    elo_map = context.get("elo_map", {})
    top4_elo = {n for n, e in elo_map.items() if e >= 1900} if elo_map else set()

    def score_row(row):
        import re
        fdrs_str = str(row.get("fdrs", ""))

        # Normalise ep_next for DGW players — divide by 1.6 to get
        # single-game equivalent so DGW doesn't artificially inflate score
        gw_numbers = re.findall(r'GW(\d+)', fdrs_str)
        is_dgw = len(gw_numbers) > len(set(gw_numbers))
        ep_normalised = row["ep_next"] / 1.6 if is_dgw else row["ep_next"]

        base = (
            row["form"] * 0.35 +
            ep_normalised * 0.45 +
            (6 - (row["avg_fdr"] if pd.notna(row["avg_fdr"]) else 3)) * 0.12 +
            (min(row["minutes"], 2700) / 2700) * 0.08
        )

        if fdrs_str and fdrs_str != "n/a":
            fdr_values = [int(x) for x in re.findall(r'\((\d)\)', fdrs_str)]
            hard_fixtures = sum(1 for f in fdr_values if f >= 4)
            base -= hard_fixtures * 0.12
            if top4_elo:
                for elite in top4_elo:
                    if elite in fdrs_str:
                        base -= 0.20
                        break
        return base

    pool["score"]      = pool.apply(score_row, axis=1)
    pool["affordable"] = pool["price"] <= budget
    pool["shortfall"]  = (pool["price"] - budget).clip(lower=0).round(1)

    return pool.sort_values(
        ["affordable", "score"], ascending=[False, False]
    ).reset_index(drop=True)


# ── summary bar ───────────────────────────────────────────────────────────────
st.markdown("---")
budget_val = pooled_bank()
budget_colour = (
    "normal" if budget_val >= 0 else "inverse"
)
c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Pooled budget",
    f"£{budget_val}m",
    delta="Over budget" if budget_val < 0 else None,
    delta_color="inverse" if budget_val < 0 else "normal"
)
c2.metric("Free transfers", free_transfers)
c3.metric("Planned",        len(transfers))
hits = hit_count()
c4.metric(
    "Hit cost",
    f"-{hits * 4} pts" if hits > 0 else "None",
    delta=f"{hits} hit(s)" if hits > 0 else "Within free transfers",
    delta_color="inverse" if hits > 0 else "normal"
)

if budget_val < 0:
    st.warning(
        f"⚠️ You are **£{abs(budget_val)}m over budget**. "
        f"Sell another player to free up funds before this plan is executable."
    )

# ── planned transfers ─────────────────────────────────────────────────────────
if transfers:
    st.markdown("---")
    st.markdown("#### Planned transfers")

    current_ep       = original_squad["ep_next"].sum()
    post_ep          = current_squad()["ep_next"].sum()
    hit_cost_preview = hit_count() * 4
    ep_gain_preview  = round(post_ep - current_ep, 1)
    net_ep_preview   = round(post_ep - hit_cost_preview, 1)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Current squad EP",  f"{current_ep:.1f}")
    m2.metric("New squad EP",      f"{post_ep:.1f}",
              delta=f"{ep_gain_preview:+.1f}")
    m3.metric("Hit cost",
              f"-{hit_cost_preview} pts" if hit_cost_preview > 0 else "Free")
    m4.metric("Net EP after hit",  f"{net_ep_preview:.1f}",
              delta=f"{round(net_ep_preview - current_ep, 1):+.1f}",
              delta_color="normal")
    m5.metric("Bank after",        f"£{pooled_bank()}m")
    st.caption(
        "EP = Expected Points across all 15 squad players. "
        "Net EP factors in hit cost. Plan is only executable when bank ≥ £0m."
    )

    for idx, t in enumerate(transfers):
        o, i    = t["out"], t["in"]
        ep_diff = round(float(i["ep_next"]) - float(o["ep_next"]), 1)
        pr_diff = round(float(i["price"])   - float(o["price"]),   1)
        is_free = idx < free_transfers

        ca, cb, cc, cd, ce = st.columns([3, 3, 2, 1, 1])
        ca.markdown(f"🔴 **{o['name']}** £{o['price']}m · EP {o['ep_next']}")
        cb.markdown(f"🟢 **{i['name']}** £{i['price']}m · EP {i['ep_next']}")
        ep_sign = "▲" if ep_diff >= 0 else "▼"
        cc.markdown(
            f"EP {ep_sign}{abs(ep_diff):.1f} · "
            f"£{'+' if pr_diff >= 0 else ''}{pr_diff}m · "
            f"{'Free' if is_free else '-4pts'}"
        )
        # Undo individual transfer
        if cd.button("↩", key=f"undo_{idx}",
                     help=f"Undo: {o['name']} → {i['name']}"):
            st.session_state["tp_transfers"].pop(idx)
            st.session_state["tp_selling"] = None
            st.session_state["tp_ai"] = None
            st.rerun()
        # Re-sell — go back to picking a replacement for this slot
        if ce.button("✏️", key=f"redo_{idx}",
                     help=f"Change replacement for {o['name']}"):
            st.session_state["tp_selling"] = o["name"]
            st.session_state["tp_transfers"].pop(idx)
            st.session_state["tp_ai"] = None
            st.rerun()

    if st.button("🗑️ Clear all transfers", type="secondary"):
        st.session_state["tp_transfers"] = []
        st.session_state["tp_selling"]   = None
        st.session_state["tp_ai"]        = None
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
        is_selling = p["name"] == selling_name
        was_bought = any(t["in"]["name"] == p["name"] for t in transfers)
        was_sold   = any(t["out"]["name"] == p["name"] for t in transfers)

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
        else:
            bg     = "rgba(255,255,255,0.03)"
            border = "0.5px solid rgba(255,255,255,0.1)"

        tag = ""
        if is_selling:
            tag = "<p style='margin:1px 0;font-size:9px;color:#E24B4A'>SELECTING...</p>"
        elif was_bought:
            tag = "<p style='margin:1px 0;font-size:9px;color:#1D9E75'>NEW</p>"
        elif was_sold:
            tag = "<p style='margin:1px 0;font-size:9px;color:rgba(255,255,255,0.3)'>SOLD</p>"

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
            elif was_bought:
                # This card is a replacement — show undo to revert
                if st.button(
                    "↩ Undo",
                    key=f"undo_card_{p['name']}",
                    use_container_width=True,
                    help=f"Revert this transfer"
                ):
                    idx = next(
                        (i for i, t in enumerate(transfers)
                         if t["in"]["name"] == p["name"]),
                        None
                    )
                    if idx is not None:
                        st.session_state["tp_transfers"].pop(idx)
                        st.session_state["tp_selling"] = None
                        st.session_state["tp_ai"] = None
                        st.rerun()

# ── replacement picker ────────────────────────────────────────────────────────
if selling_name:
    selling_rows = original_squad[original_squad["name"] == selling_name]
    chain_original_name = None

    if not selling_rows.empty:
        selling_player = selling_rows.iloc[0]
    else:
        for t in transfers:
            if t["in"]["name"] == selling_name:
                chain_original_name = t["out"]["name"]
                selling_player = t["in"]
                break

    out_pos = selling_player["position"]
    budget  = round(pooled_bank() + float(selling_player["price"]), 1)

    st.markdown("---")
    st.markdown(
        f"#### Replacements for **{selling_name}** "
        f"({out_pos} · £{selling_player['price']}m · EP {selling_player['ep_next']})"
    )
    st.caption(
        f"Current budget: £{budget}m · Position: {out_pos} only · "
        f"Over-budget options shown — sell more players to unlock them"
    )

    pool = available_replacements(out_pos, selling_player)

    if pool.empty:
        st.warning(f"No available {out_pos} players found.")
    else:
        affordable   = pool[pool["affordable"]].head(12)
        over_budget  = pool[~pool["affordable"]].head(8)

        # ── Affordable options ──
        if not affordable.empty:
            st.markdown("**Within budget:**")
            n = min(4, len(affordable))
            for row_i in range(-(-len(affordable) // n)):
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
                            f'border-radius:8px;padding:8px 4px;text-align:center">'
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
                            f'{str(p["fdrs"])[:30]}</p>'
                            f'</div>',
                            unsafe_allow_html=True
                        )
                        if st.button("Buy", key=f"buy_{p['name']}",
                                     use_container_width=True):
                            slot_original = (
                                chain_original_name
                                if chain_original_name
                                else selling_name
                            )
                            existing_idx = next(
                                (i for i, t in enumerate(
                                    st.session_state["tp_transfers"])
                                 if t["out"]["name"] == slot_original),
                                None
                            )
                            if existing_idx is not None:
                                st.session_state["tp_transfers"][existing_idx] = {
                                    "out": st.session_state[
                                        "tp_transfers"][existing_idx]["out"],
                                    "in":  p,
                                }
                            else:
                                st.session_state["tp_transfers"].append({
                                    "out": selling_player,
                                    "in":  p,
                                })
                            st.session_state["tp_selling"] = None
                            st.rerun()

        # ── Over-budget options ──
        if not over_budget.empty:
            st.markdown("---")
            st.markdown(
                "**💸 Premium targets** *(over budget — sell more players "
                "to unlock these)*"
            )
            n = min(4, len(over_budget))
            for row_i in range(-(-len(over_budget) // n)):
                row_players = over_budget.iloc[row_i * n: row_i * n + n]
                cols = st.columns(n)
                for col, (_, p) in zip(cols, row_players.iterrows()):
                    ep_col = (
                        "#1D9E75" if p["ep_next"] >= 6
                        else "#BA7517" if p["ep_next"] >= 4
                        else "#E24B4A"
                    )
                    shortfall = p["shortfall"]
                    with col:
                        st.markdown(
                            f'<div style="background:rgba(186,117,23,0.08);'
                            f'border:0.5px solid rgba(186,117,23,0.35);'
                            f'border-radius:8px;padding:8px 4px;text-align:center">'
                            f'<p style="margin:0;font-size:11px;font-weight:600;'
                            f'white-space:nowrap;overflow:hidden;'
                            f'text-overflow:ellipsis">{p["name"]}</p>'
                            f'<p style="margin:1px 0;font-size:10px;'
                            f'color:rgba(255,255,255,0.45)">'
                            f'£{p["price"]}m · {p["team"]}</p>'
                            f'<p style="margin:0;font-size:11px;font-weight:600;'
                            f'color:{ep_col}">EP {p["ep_next"]}</p>'
                            f'<p style="margin:1px 0;font-size:9px;'
                            f'color:#BA7517;font-weight:500">'
                            f'£{shortfall}m needed</p>'
                            f'<p style="margin:1px 0;font-size:9px;'
                            f'color:rgba(255,255,255,0.3)">'
                            f'{str(p["fdrs"])[:30]}</p>'
                            f'</div>',
                            unsafe_allow_html=True
                        )
                        # Allow buying even if over budget
                        # Budget goes negative — warning shown at top
                        if st.button(
                            f"Buy (£{shortfall}m short)",
                            key=f"buy_ob_{p['name']}",
                            use_container_width=True
                        ):
                            slot_original = (
                                chain_original_name
                                if chain_original_name
                                else selling_name
                            )
                            existing_idx = next(
                                (i for i, t in enumerate(
                                    st.session_state["tp_transfers"])
                                 if t["out"]["name"] == slot_original),
                                None
                            )
                            if existing_idx is not None:
                                st.session_state["tp_transfers"][existing_idx] = {
                                    "out": st.session_state[
                                        "tp_transfers"][existing_idx]["out"],
                                    "in":  p,
                                }
                            else:
                                st.session_state["tp_transfers"].append({
                                    "out": selling_player,
                                    "in":  p,
                                })
                            st.session_state["tp_selling"] = None
                            st.rerun()

# ── final verdict ─────────────────────────────────────────────────────────────
if transfers:
    st.markdown("---")
    st.subheader("📊 Plan summary")

    current_ep = original_squad["ep_next"].sum()
    post_ep    = current_squad()["ep_next"].sum()
    hit_cost   = hit_count() * 4
    net_ep     = round(post_ep - hit_cost, 1)
    ep_gain    = round(post_ep - current_ep, 1)
    final_bank = pooled_bank()

    executable = final_bank >= 0

    if not executable:
        st.error(
            f"❌ Plan not executable — £{abs(final_bank)}m over budget. "
            f"Sell another player to balance the books."
        )
    elif hit_cost == 0:
        st.success(
            f"✅ Within free transfers. "
            f"Squad EP {current_ep:.1f} → {post_ep:.1f} "
            f"(+{ep_gain:.1f} pts)."
        )
    elif net_ep > current_ep:
        st.success(
            f"✅ Worth the hit. Squad EP {current_ep:.1f} → {post_ep:.1f} "
            f"(+{ep_gain:.1f}), net {net_ep:.1f} after -{hit_cost} pt cost."
        )
    elif net_ep == current_ep:
        st.warning(
            f"⚠️ Break even. Only do this if forced by injury."
        )
    else:
        st.error(
            f"❌ Not worth it. You lose "
            f"{round(current_ep - net_ep, 1):.1f} pts net. Roll."
        )

    if hit_cost > 0 and ep_gain > 0:
        breakeven = round(hit_cost / (ep_gain / len(transfers)), 1)
        st.caption(
            f"Breakeven: ~{breakeven} GWs to recover "
            f"the -{hit_cost} pt cost."
        )

    st.markdown("---")
    if executable and st.button(
        "🤖 Get AI verdict on this plan",
        type="primary",
        use_container_width=True
    ):
        with st.spinner("Analysing..."):
            analyses = []
            for idx, t in enumerate(transfers):
                is_free = idx < free_transfers
                a = get_hit_analysis(
                    player_out=t["out"],
                    player_in=t["in"],
                    context=context,
                    is_free_transfer=is_free
                )
                if a:
                    analyses.append(
                        f"**{t['out']['name']} → {t['in']['name']}** "
                        f"{'(free)' if is_free else '(-4 pts hit)'}\n\n{a}"
                    )
            st.session_state["tp_ai"] = "\n\n---\n\n".join(analyses)

    elif not executable:
        st.info(
            "AI verdict available once your plan is within budget."
        )

    if st.session_state.get("tp_ai"):
        st.markdown(st.session_state["tp_ai"])