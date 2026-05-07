import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import streamlit as st
import pandas as pd
import requests
from odds_fetcher import get_premier_league_odds, build_team_odds_map
from data_enricher import FPL_TO_ODDS_TEAM
from config import FPL_BASE_URL, FPL_HEADERS
from fetcher import get_current_gameweek

st.set_page_config(page_title="GW Projections", page_icon="📊", layout="wide")

ODDS_TO_FPL = {v: k for k, v in FPL_TO_ODDS_TEAM.items()}

@st.cache_data(ttl=3600)
def load_data():
    bootstrap = requests.get(
        f"{FPL_BASE_URL}/bootstrap-static/", headers=FPL_HEADERS, timeout=10
    ).json()
    fpl_fixtures = requests.get(
        f"{FPL_BASE_URL}/fixtures/", headers=FPL_HEADERS, timeout=10
    ).json()
    odds_data = get_premier_league_odds()
    return bootstrap, fpl_fixtures, odds_data

try:
    with st.spinner("Fetching data..."):
        bootstrap, fpl_fixtures, odds_data = load_data()
except Exception as e:
    st.error(f"Could not load data: {e}")
    st.stop()

current_gw  = get_current_gameweek(bootstrap)
upcoming_gw = current_gw + 1
team_map    = {t["id"]: t["short_name"] for t in bootstrap["teams"]}

gw_fixtures = [
    f for f in fpl_fixtures
    if f["event"] == upcoming_gw and not f["finished"]
]
if not gw_fixtures:
    upcoming_gw = current_gw
    gw_fixtures = [f for f in fpl_fixtures if f["event"] == upcoming_gw and not f["finished"]]

# Build consensus odds map (odds full name -> signals)
odds_map = build_team_odds_map(odds_data)
# Index by FPL short name for easy lookup
fpl_odds = {}
for odds_name, signals in odds_map.items():
    fpl_short = ODDS_TO_FPL.get(odds_name)
    if fpl_short:
        fpl_odds[fpl_short] = signals

# Build per-team rows for the upcoming GW only
rows = []
for f in gw_fixtures:
    h = team_map[f["team_h"]]
    a = team_map[f["team_a"]]
    h_sig = fpl_odds.get(h, {})
    a_sig = fpl_odds.get(a, {})
    rows.append({
        "Team":       h,
        "Opponent":   a,
        "H/A":        "H",
        "Proj Goals": h_sig.get("proj_goals"),
        "CS %":       h_sig.get("cs_prob"),
        "Win %":      h_sig.get("win_prob"),
        "Over 2.5 %": h_sig.get("over25_prob"),
    })
    rows.append({
        "Team":       a,
        "Opponent":   h,
        "H/A":        "A",
        "Proj Goals": a_sig.get("proj_goals"),
        "CS %":       a_sig.get("cs_prob"),
        "Win %":      a_sig.get("win_prob"),
        "Over 2.5 %": a_sig.get("over25_prob"),
    })

df = pd.DataFrame(rows)
for col in ["Proj Goals", "CS %", "Win %", "Over 2.5 %"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")

st.title(f"📊 GW{upcoming_gw} Projections")
st.caption(
    "Consensus bookmaker probabilities for the upcoming gameweek. "
    "Projected goals and clean sheet % are split per team from match odds."
)

if df.empty or df["Proj Goals"].isna().all():
    st.info("No odds data available for the upcoming gameweek yet.")
    st.stop()

col_goals, col_cs = st.columns(2)

with col_goals:
    st.subheader("⚔️ Projected Goals")
    st.caption("Per-team expected goals, split from match total by win probability.")
    st.caption("🔁 = Double Gameweek — team plays twice this GW")

    goals_df = (
        df[["Team", "Opponent", "H/A", "Proj Goals", "Over 2.5 %"]]
        .dropna(subset=["Proj Goals"])
        .sort_values("Proj Goals", ascending=False)
        .reset_index(drop=True)
    )

    for _, row in goals_df.iterrows():
        goals = row["Proj Goals"]
        o25   = row["Over 2.5 %"]
        colour = (
            "#1D9E75" if goals >= 1.8
            else "#BA7517" if goals >= 1.3
            else "rgba(255,255,255,0.45)"
        )
        o25_str = f"  ·  {o25:.0f}% o2.5" if pd.notna(o25) else ""
        
        # Flag DGW teams
        dgw_flag = " 🔁" if goals_df["Team"].tolist().count(row["Team"]) > 1 else ""
        
        st.markdown(
            f'<div style="display:flex;align-items:center;'
            f'padding:5px 8px;border-bottom:0.5px solid rgba(255,255,255,0.07)">'
            f'<span style="font-size:13px;font-weight:600;width:52px">'
            f'{row["Team"]}{dgw_flag}</span>'
            f'<span style="font-size:11px;color:rgba(255,255,255,0.4);width:100px">'
            f'vs {row["Opponent"]} ({row["H/A"]})</span>'
            f'<span style="font-size:14px;color:{colour};font-weight:700;width:44px">'
            f'{goals:.2f}</span>'
            f'<span style="font-size:11px;color:rgba(255,255,255,0.35)">'
            f'{o25_str}</span>'
            f'</div>',
            unsafe_allow_html=True
        )

with col_cs:
    st.subheader("🛡️ Clean Sheet %")
    st.caption("Estimated from opponent's projected goals. Key for GK & DEF picks.")
    st.caption("🔁 = Double Gameweek — team plays twice this GW")

    cs_df = (
        df[["Team", "Opponent", "H/A", "CS %", "Win %"]]
        .dropna(subset=["CS %"])
        .sort_values("CS %", ascending=False)
        .reset_index(drop=True)
    )

    for _, row in cs_df.iterrows():
        cs     = row["CS %"]
        win    = row["Win %"]
        colour = (
            "#1D9E75" if cs >= 38
            else "#BA7517" if cs >= 26
            else "rgba(255,255,255,0.45)"
        )
        win_str = f"  ·  {win:.0f}% win" if pd.notna(win) else ""
        dgw_flag = " 🔁" if cs_df["Team"].tolist().count(row["Team"]) > 1 else ""

        st.markdown(
            f'<div style="display:flex;align-items:center;'
            f'padding:5px 8px;border-bottom:0.5px solid rgba(255,255,255,0.07)">'
            f'<span style="font-size:13px;font-weight:600;width:52px">'
            f'{row["Team"]}{dgw_flag}</span>'
            f'<span style="font-size:11px;color:rgba(255,255,255,0.4);width:100px">'
            f'vs {row["Opponent"]} ({row["H/A"]})</span>'
            f'<span style="font-size:14px;color:{colour};font-weight:700;width:50px">'
            f'{cs:.0f}%</span>'
            f'<span style="font-size:11px;color:rgba(255,255,255,0.35)">'
            f'{win_str}</span>'
            f'</div>',
            unsafe_allow_html=True
        )

st.markdown("---")
st.caption(
    f"GW{upcoming_gw} only. Projected goals = match total × team win share. "
    "CS% = max(0, 55 − opp_proj_goals × 22). Consensus across all available bookmakers."
)
