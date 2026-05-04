import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fetcher import fetch_all
from transformer import build_recommendation_context

import streamlit as st
import pandas as pd
from fetcher import fetch_all
from transformer import build_player_dataframe, find_differentials
from data_enricher import get_enriched_player_stats

st.set_page_config(page_title="Differentials", page_icon="🔍")
st.title("🔍 Differential Finder")
st.caption("High-form, low-ownership players the top managers are quietly targeting.")

col1, col2, col3 = st.columns(3)
with col1:
    max_ownership = st.slider("Max ownership %", 5, 30, 15)
with col2:
    min_form = st.slider("Min form", 3.0, 10.0, 5.0, step=0.5)
with col3:
    position_filter = st.multiselect(
        "Position",
        ["GK", "DEF", "MID", "FWD"],
        default=["DEF", "MID", "FWD"]
    )

if st.button("Find Differentials", type="primary"):
    with st.spinner("Scanning 830 players..."):
        # Use cached data if available
        if "data" not in st.session_state:
            data = fetch_all(11)  # use a dummy ID just for bootstrap
            st.session_state["bootstrap_data"] = data
        else:
            data = st.session_state["data"]

        player_df = build_player_dataframe(
            data["bootstrap"], data["fixtures"]
        )

        diffs = find_differentials(
            player_df,
            data["current_gw"],
            max_ownership=max_ownership,
            min_form=min_form
        )

        if position_filter:
            diffs = diffs[diffs["position"].isin(position_filter)]

    if diffs.empty:
        st.warning("No differentials found with these filters. Try loosening them.")
    else:
        st.success(f"Found {len(diffs)} differentials")
        st.dataframe(
            diffs.rename(columns={
                "name": "Player",
                "team": "Team",
                "position": "Pos",
                "price": "Price",
                "form": "Form",
                "ep_next": "EP Next",
                "selected_pct": "Owned %",
                "fdrs": "Fixtures",
                "differential_score": "Score"
            }),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Price": st.column_config.NumberColumn(format="£%.1f"),
                "Owned %": st.column_config.NumberColumn(format="%.1f%%"),
                "Score": st.column_config.NumberColumn(format="%.2f"),
            }
        )

        st.markdown("---")
        st.caption(
            "Score = weighted combination of form, expected points, "
            "fixture difficulty, and ownership penalty. "
            "Lower ownership = higher differential value."
        )