import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import streamlit as st
import pandas as pd
from fetcher import fetch_all
from transformer import build_recommendation_context, build_player_dataframe
from data_enricher import enrich_context
from llm import get_hit_analysis

st.set_page_config(page_title="Hit Calculator", page_icon="🎯")

st.title("🎯 Hit Calculator")
st.caption("Is taking a -4 point hit worth it? Find out before you commit.")

# --- Team ID input ---
team_id_input = st.text_input(
    "Enter your FPL Team ID",
    placeholder="e.g. 81578",
    value=str(st.session_state.get("last_team_id", "")),
    help="Same ID used in Transfer Hub"
)

load_button = st.button("Load My Team", type="primary")

if load_button:
    if not team_id_input.strip():
        st.error("Please enter a team ID.")
        st.stop()

    try:
        team_id = int(team_id_input.strip())
    except ValueError:
        st.error("Team ID must be a number.")
        st.stop()

    # Use cached data if same team ID
    if (st.session_state.get("last_team_id") != team_id or
            "context" not in st.session_state):

        with st.spinner("Loading your squad..."):
            try:
                data = fetch_all(team_id)
                context = build_recommendation_context(
                    team_info=data["team_info"],
                    picks=data["picks"],
                    bootstrap=data["bootstrap"],
                    fixtures=data["fixtures"]
                )
                context = enrich_context(context, data["current_gw"])
                st.session_state["data"] = data
                st.session_state["context"] = context
                st.session_state["last_team_id"] = team_id
                st.success(f"Loaded squad for "
                           f"{data['team_info']['player_first_name']} "
                           f"{data['team_info']['player_last_name']}")
            except Exception as e:
                st.error(f"Could not load team: {e}")
                st.stop()
    else:
        data = st.session_state["data"]
        context = st.session_state["context"]
        st.info("Using cached squad data.")

# --- Hit calculator UI (only shows after team is loaded) ---
if "context" in st.session_state:
    context = st.session_state["context"]
    data = st.session_state["data"]

    squad = context["squad"]
    candidates = context["candidates"]

    st.markdown("---")
    st.subheader("Select your transfer")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Player OUT** (from your squad)")
        player_out_name = st.selectbox(
            "Who are you selling?",
            options=squad["name"].tolist(),
            key="player_out"
        )
        # Show selected player stats
        out_player = squad[squad["name"] == player_out_name].iloc[0]
        st.markdown(
            f'<div style="background:var(--color-background-secondary);'
            f'border-radius:8px;padding:12px;margin-top:8px;'
            f'border:0.5px solid var(--color-border-tertiary)">'
            f'<p style="margin:0;font-size:13px;color:var(--color-text-secondary)">Price</p>'
            f'<p style="margin:0;font-size:16px;font-weight:500">£{out_player["price"]}m</p>'
            f'<p style="margin:4px 0 0;font-size:13px;color:var(--color-text-secondary)">Form</p>'
            f'<p style="margin:0;font-size:16px;font-weight:500">{out_player["form"]}</p>'
            f'<p style="margin:4px 0 0;font-size:13px;color:var(--color-text-secondary)">EP Next</p>'
            f'<p style="margin:0;font-size:16px;font-weight:500">{out_player["ep_next"]}</p>'
            f'<p style="margin:4px 0 0;font-size:13px;color:var(--color-text-secondary)">Fixtures</p>'
            f'<p style="margin:0;font-size:13px">{out_player["fdrs"]}</p>'
            f'<p style="margin:4px 0 0;font-size:13px;color:var(--color-text-secondary)">Status</p>'
            f'<p style="margin:0;font-size:13px">{"🔴 Injured" if out_player["status"] == "i" else "🟡 Doubtful" if out_player["status"] == "d" else "🟢 Available"}</p>'
            f'</div>',
            unsafe_allow_html=True
        )

    with col2:
        st.markdown("**Player IN** (transfer target)")

        # Get position of player out to filter candidates
        out_position = out_player["position"]
        pos_candidates = candidates.get(out_position, pd.DataFrame())

        if pos_candidates.empty:
            st.warning(f"No candidates found for {out_position} position.")
            st.stop()

        # Also allow searching all available players
        search_mode = st.toggle("Search all players", value=False)

        if search_mode:
            # Build full player df for search
            all_players = data["bootstrap"]["elements"]
            all_df = pd.DataFrame([{
                "name": p["web_name"],
                "position": ["", "GK", "DEF", "MID", "FWD"][p["element_type"]],
                "price": p["now_cost"] / 10,
                "form": float(p["form"] or 0),
                "ep_next": float(p["ep_next"] or 0),
                "status": p["status"],
                "fdrs": "n/a"
            } for p in all_players
                if p["status"] == "a"
                and ["", "GK", "DEF", "MID", "FWD"][p["element_type"]] == out_position
            ])
            candidate_names = all_df["name"].tolist()
            candidate_df = all_df
        else:
            candidate_names = pos_candidates["name"].tolist()
            candidate_df = pos_candidates

        player_in_name = st.selectbox(
            "Who are you buying?",
            options=candidate_names,
            key="player_in"
        )

        # Show selected candidate stats
        in_player = candidate_df[
            candidate_df["name"] == player_in_name
        ].iloc[0]

        budget = out_player["price"] + context["bank"]
        affordable = in_player["price"] <= budget

        border_color = (
            "var(--color-border-success)" if affordable
            else "var(--color-border-danger)"
        )

        st.markdown(
            f'<div style="background:var(--color-background-secondary);'
            f'border-radius:8px;padding:12px;margin-top:8px;'
            f'border:0.5px solid {border_color}">'
            f'<p style="margin:0;font-size:13px;color:var(--color-text-secondary)">Price</p>'
            f'<p style="margin:0;font-size:16px;font-weight:500">£{in_player["price"]}m '
            f'{"✅" if affordable else "❌ Over budget"}</p>'
            f'<p style="margin:4px 0 0;font-size:13px;color:var(--color-text-secondary)">Form</p>'
            f'<p style="margin:0;font-size:16px;font-weight:500">{in_player["form"]}</p>'
            f'<p style="margin:4px 0 0;font-size:13px;color:var(--color-text-secondary)">EP Next</p>'
            f'<p style="margin:0;font-size:16px;font-weight:500">{in_player["ep_next"]}</p>'
            f'<p style="margin:4px 0 0;font-size:13px;color:var(--color-text-secondary)">Fixtures</p>'
            f'<p style="margin:0;font-size:13px">{in_player["fdrs"]}</p>'
            f'</div>',
            unsafe_allow_html=True
        )

    # --- Quick stats comparison ---
    st.markdown("---")
    st.subheader("📊 Quick comparison")

    ep_diff = round(in_player["ep_next"] - out_player["ep_next"], 1)
    form_diff = round(float(in_player["form"]) - float(out_player["form"]), 1)
    breakeven_gws = round(4 / ep_diff, 1) if ep_diff > 0 else None

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        "EP gain next GW",
        f"+{ep_diff}" if ep_diff > 0 else str(ep_diff),
        delta=None
    )
    m2.metric(
        "Form difference",
        f"+{form_diff}" if form_diff > 0 else str(form_diff),
        delta=None
    )
    m3.metric(
        "Breakeven",
        f"{breakeven_gws} GWs" if breakeven_gws else "Never" if ep_diff <= 0 else "Instant",
        help="GWs needed to recover the -4 point cost"
    )
    m4.metric(
        "Budget headroom",
        f"£{round(budget - in_player['price'], 1)}m"
    )

    # Verdict banner
    if not affordable:
        st.error("❌ You cannot afford this transfer with your current budget.")
    elif ep_diff <= 0:
        st.error("❌ The player coming in has a lower or equal EP. "
                 "This hit is not worth taking.")
    elif breakeven_gws and breakeven_gws <= 2:
        st.success(f"✅ Strong hit. You break even in {breakeven_gws} GWs — "
                   f"the numbers strongly support this transfer.")
    elif breakeven_gws and breakeven_gws <= 4:
        st.warning(f"⚠️ Marginal hit. Breakeven in {breakeven_gws} GWs. "
                   f"Get the AI analysis before deciding.")
    else:
        st.error(f"❌ Weak hit. Breakeven takes {breakeven_gws}+ GWs. "
                 f"Consider waiting for a free transfer.")

    # --- AI deep analysis ---
    st.markdown("---")
    st.subheader("🤖 AI Breakeven Analysis")

    analyse_button = st.button(
        "Get full AI analysis ↗",
        type="primary",
        disabled=not affordable
    )

    if analyse_button:
        with st.spinner("Analysing transfer value..."):
            analysis = get_hit_analysis(
                player_out=out_player,
                player_in=in_player,
                context=context
            )
        st.markdown(analysis)