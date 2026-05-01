# app.py
import requests
import streamlit as st
from fetcher import fetch_all
from transformer import build_recommendation_context
from data_enricher import enrich_context
from llm import get_recommendation
from fixture_planner import build_season_plan

st.set_page_config(
    page_title="FPL Assistant Manager",
    page_icon="⚽",
    layout="centered"
)

st.title("⚽ FPL Assistant Manager")
st.caption("AI-powered transfer recommendations using live FPL data.")

team_id_input = st.text_input(
    "Enter your FPL Team ID",
    placeholder="e.g. 81578",
    help="Find your ID in the URL on fantasy.premierleague.com"
)

run_button = st.button("Get Transfer Recommendation", type="primary")


if run_button:
    if not team_id_input.strip():
        st.error("Please enter a team ID.")
        st.stop()

    try:
        team_id = int(team_id_input.strip())
        if team_id <= 0:
            raise ValueError
    except ValueError:
        st.error("Team ID must be a positive whole number.")
        st.stop()

    try:
        with st.status("Fetching your FPL data...", expanded=True) as status:
            st.write("Connecting to FPL API...")
            data = fetch_all(team_id)
            st.write(f"✅ GW{data['current_gw']} data fetched for "
                     f"**{data['team_info']['player_first_name']} "
                     f"{data['team_info']['player_last_name']}**")

            st.write("Building squad and candidate list...")
            context = build_recommendation_context(
                team_info=data["team_info"],
                picks=data["picks"],
                bootstrap=data["bootstrap"],
                fixtures=data["fixtures"]
            )

            st.write("Enriching with xG, Elo, and availability data...")
            context = enrich_context(context, data["current_gw"])
            st.write("✅ Enrichment complete")

            st.write("Building season fixture plan...")
            season_plan = build_season_plan(
                bootstrap=data["bootstrap"],
                fixtures=data["fixtures"],
                squad=context["squad"],
                candidates=context["candidates"],
                current_gw=data["current_gw"]
            )
            context["season_plan"] = season_plan
            st.write("✅ Season plan built")

            st.write("Generating AI recommendation...")
            recommendation = get_recommendation(context, data["free_transfers"])
            status.update(label="✅ Analysis complete!", state="complete")

            # Detect free hit was played
            active_chip = data["picks"].get("active_chip", None)
            if active_chip == "freehit":
                st.warning(
                    "⚠️ **Free Hit detected:** Your squad shown is the Free Hit team from last "
                    "gameweek, not your current squad. Your real team will appear after the next "
                    "deadline passes. For now, manually verify the squad shown matches your actual team."
                    )

        # --- Team summary metrics ---
        st.subheader(f"📋 {context['team_name']}")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Manager", f"{data['team_info']['player_first_name']} "
                               f"{data['team_info']['player_last_name']}")
        col2.metric("Overall Rank", f"{data['team_info']['summary_overall_rank']:,}")
        col3.metric("Bank", f"£{context['bank']}m")
        col4.metric("Free Transfers", data["free_transfers"])

        # --- INJURY ALERTS FIRST ---
        squad = context["squad"]
        injured = squad[squad["status"] == "i"]
        doubtful = squad[squad["status"] == "d"]

        if not injured.empty or not doubtful.empty:
            st.subheader("🚨 Injury & Availability Alerts")
            for _, p in injured.iterrows():
                news = p.get("news", "") or "No details available"
                st.error(f"🔴 **{p['name']}** (£{p['price']}m) — "
                         f"Injured | 0% chance of playing | {news}")
            for _, p in doubtful.iterrows():
                chance = p.get("chance_of_playing_next_round")
                chance_str = f"{int(chance)}%" if chance == chance else "Unknown"
                news = p.get("news", "") or "No details available"
                st.warning(f"🟡 **{p['name']}** (£{p['price']}m) — "
                           f"Doubtful | {chance_str} chance | {news}")

        # --- Squad table ---
        with st.expander("👥 Your Current Squad", expanded=False):
            display = squad[["name", "position", "price", "form",
                             "ep_next", "fdrs", "status",
                             "chance_of_playing_next_round"]].copy()

            # Clean up NaN chance % — 100% if no injury concern
            display["chance_of_playing_next_round"] = (
                display["chance_of_playing_next_round"]
                .fillna(100)
                .astype(int)
                .astype(str) + "%"
            )

            display.columns = ["Name", "Pos", "Price", "Form",
                               "EP Next", "Fixtures (FDR)", "Status", "Chance %"]

            st.dataframe(
                display,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Status": st.column_config.Column(width="small"),
                    "Chance %": st.column_config.Column(width="small"),
                    "Price": st.column_config.NumberColumn(format="£%.1f"),
                }
            )

        # --- AI Recommendation ---
        st.subheader("🤖 AI Transfer Recommendation")
        st.markdown(recommendation)

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            st.error(f"Team ID {team_id} not found. "
                     f"Please check your ID and try again.")
        else:
            st.error(f"FPL API error: {e}")
    except Exception as e:
        st.error(f"Something went wrong: {e}")
        st.info("Please check your team ID and try again.")