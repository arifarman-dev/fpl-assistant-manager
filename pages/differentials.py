import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import streamlit as st
import pandas as pd
from fetcher import fetch_all
from transformer import build_player_dataframe, find_differentials
from llm import get_differential_insight

if "data" not in st.session_state:
    st.info("👈 Please load your team in the Transfer Hub first.")
    st.stop()

st.set_page_config(page_title="Differentials", page_icon="🔍")

st.title("🔍 Differential Finder")
st.caption(
    "High-form, low-ownership players the top managers are quietly targeting. "
    "Updated every gameweek."
)

st.markdown("---")

# --- Load data ---
if "data" not in st.session_state:
    with st.spinner("Loading player data..."):
        try:
            # Use a known valid team ID just to bootstrap data
            # User doesn't need to enter their ID for differentials
            data = fetch_all(1)
            st.session_state["data"] = data
        except Exception as e:
            st.error(f"Could not load FPL data: {e}")
            st.stop()
else:
    data = st.session_state["data"]

player_df = build_player_dataframe(data["bootstrap"], data["fixtures"])

# --- Position tabs ---
tab_all, tab_gk, tab_def, tab_mid, tab_fwd = st.tabs([
    "All", "Goalkeepers", "Defenders", "Midfielders", "Forwards"
])

def render_differential_table(df: pd.DataFrame, position_filter: str = None):
    """Render a clean differential table for a given position."""
    if position_filter:
        filtered = df[df["position"] == position_filter]
    else:
        filtered = df

    if filtered.empty:
        st.info("No differentials found for this position.")
        return

    # Display table
    display = filtered[[
        "name", "team", "position", "price",
        "form", "ep_next", "selected_pct", "fdrs"
    ]].copy()

    display.columns = [
        "Player", "Team", "Pos", "Price",
        "Form", "EP Next", "Owned %", "Fixtures (FDR)"
    ]

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Price": st.column_config.NumberColumn(format="£%.1fm"),
            "Owned %": st.column_config.NumberColumn(format="%.1f%%"),
            "Form": st.column_config.NumberColumn(format="%.1f"),
            "EP Next": st.column_config.NumberColumn(format="%.1f"),
        }
    )

    insight_key = f"insight_{position_filter or 'all'}"

    if st.button(
        "Get AI insight on these differentials ↗",
        key=f"btn_{position_filter or 'all'}"
    ):
        with st.spinner("Generating insight..."):
            insight = get_differential_insight(filtered, data["current_gw"])
            st.session_state[insight_key] = insight

    # Display cached insight if it exists
    if insight_key in st.session_state:
        st.markdown(st.session_state[insight_key])


# Find differentials — no user input needed
diffs = find_differentials(
    player_df,
    data["current_gw"],
    max_ownership=15.0,
    min_form=4.5,
    top_n=20
)

with tab_all:
    st.markdown(
        f"**{len(diffs)} differentials found** — owned by fewer than 15% "
        f"of managers, form 4.5+, available, and playing regular minutes."
    )
    render_differential_table(diffs)

with tab_gk:
    render_differential_table(diffs, "GK")

with tab_def:
    render_differential_table(diffs, "DEF")

with tab_mid:
    render_differential_table(diffs, "MID")

with tab_fwd:
    render_differential_table(diffs, "FWD")