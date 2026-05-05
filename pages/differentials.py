import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import streamlit as st
import pandas as pd
from transformer import build_player_dataframe, find_differentials
from llm import get_differential_insight

st.set_page_config(page_title="Differentials", page_icon="🔍")

if "data" not in st.session_state:
    st.info("👈 Please load your team in the Transfer Hub first.")
    st.stop()

data = st.session_state["data"]

st.title("🔍 Differential Finder")
st.caption(
    "High-form, low-ownership players the top managers are quietly targeting. "
    "Owned by fewer than 15% of managers, in form, and playing regularly."
)

player_df = build_player_dataframe(data["bootstrap"], data["fixtures"])

# Fixed criteria — no sliders, no developer inputs
diffs = find_differentials(
    player_df,
    data["current_gw"],
    max_ownership=15.0,
    min_form=4.5,
    top_n=30
)

if diffs.empty:
    st.info("No differentials found this gameweek. Check back after the next deadline.")
    st.stop()

# Position filter — simple buttons, not a dropdown
pos_options = ["All", "GK", "DEF", "MID", "FWD"]
selected_pos = st.radio("Filter by position", pos_options, horizontal=True)

filtered = diffs if selected_pos == "All" else diffs[diffs["position"] == selected_pos]

st.markdown(f"**{len(filtered)} players found**")

if filtered.empty:
    st.info(f"No {selected_pos} differentials this week.")
    st.stop()

# Clean display table
display = filtered[[
    "name", "team", "position", "price",
    "form", "ep_next", "selected_pct", "fdrs"
]].copy()
display.columns = ["Player", "Team", "Pos", "Price", "Form", "EP Next", "Owned %", "Fixtures"]

st.dataframe(
    display,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Price":    st.column_config.NumberColumn(format="£%.1fm"),
        "Owned %":  st.column_config.NumberColumn(format="%.1f%%"),
        "Form":     st.column_config.NumberColumn(format="%.1f"),
        "EP Next":  st.column_config.NumberColumn(format="%.1f"),
        "Fixtures": st.column_config.TextColumn(width="large"),
    }
)

st.markdown("---")

# Single AI insight button
if st.button("🤖 Who should I target?", type="primary", use_container_width=True):
    with st.spinner("Analysing differentials..."):
        insight = get_differential_insight(filtered, data["current_gw"])
        st.session_state["diff_insight"] = insight

if "diff_insight" in st.session_state:
    st.markdown(st.session_state["diff_insight"])
