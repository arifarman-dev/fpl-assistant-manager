import requests
import streamlit as st
import pandas as pd
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
st.markdown("""
Your AI-powered FPL edge. Built for managers who want data-driven decisions, 
not gut feelings.
""")

col1, col2, col3 = st.columns(3)
with col1:
    st.info("🔄 **Transfer Hub**\nAI recommendations personalised to your squad")
with col2:
    st.info("🔍 **Differentials**\nHigh-form, low-ownership gems others are missing")
with col3:
    st.info("📅 **Fixture Planner**\nDGW/BGW calendar with chip strategy")

st.markdown("---")
st.caption("Enter your FPL team ID in any section to get started.")

# --- Input ---
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

    # --- Session state cache check ---
    if (st.session_state.get("last_team_id") != team_id or
            "context" not in st.session_state):

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
                context["chip_status"] = data["chip_status"]
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
                recommendation = get_recommendation(
                    context, data["free_transfers"]
                )
                st.write("✅ Recommendation ready")

                status.update(label="✅ Analysis complete!", state="complete")

            # Cache everything
            st.session_state["data"] = data
            st.session_state["context"] = context
            st.session_state["recommendation"] = recommendation
            st.session_state["last_team_id"] = team_id

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                st.error(f"Team ID {team_id} not found. "
                         f"Please check your ID and try again.")
            else:
                st.error(f"FPL API error: {e}")
            st.stop()
        except Exception as e:
            st.error(f"Something went wrong: {e}")
            st.info("Please check your team ID and try again.")
            st.stop()

    else:
        # Use cached data
        data = st.session_state["data"]
        context = st.session_state["context"]
        recommendation = st.session_state["recommendation"]
        st.info("Using cached data. Re-enter your team ID and click again to refresh.")

    # --- Free Hit warning ---
    active_chip = data["picks"].get("active_chip", None)
    if active_chip == "freehit":
        st.warning(
            "⚠️ **Free Hit detected:** Your squad shown is the Free Hit team "
            "from last gameweek, not your current squad. Your real team will "
            "appear after the next deadline passes."
        )

    # --- Team summary metrics ---
    st.subheader(f"📋 {context['team_name']}")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Manager", f"{data['team_info']['player_first_name']} "
                           f"{data['team_info']['player_last_name']}")
    col2.metric("Overall Rank",
                f"{data['team_info']['summary_overall_rank']:,}")
    col3.metric("Bank", f"£{context['bank']}m")
    col4.metric("Free Transfers", data["free_transfers"])

    # --- Injury alerts ---
    squad = context["squad"]
    injured = squad[squad["status"] == "i"]
    doubtful = squad[squad["status"] == "d"]

    def render_pitch_view(squad: pd.DataFrame):
        """Render squad as a football pitch with player cards."""

        def ep_color(ep):
            if ep >= 7:  return "color:#1D9E75;font-weight:500"
            if ep >= 4:  return "color:#BA7517;font-weight:500"
            return "color:#E24B4A;font-weight:500"

        def status_badge(row):
            if row["status"] == "i":
                return '<span style="background:#FCEBEB;color:#791F1F;font-size:10px;padding:1px 5px;border-radius:4px;display:inline-block;margin-top:2px">Injured</span>'
            if row["status"] == "d":
                chance = row.get("chance_of_playing_next_round", "?")
                chance = int(chance) if pd.notna(chance) else "?"
                return f'<span style="background:#FAEEDA;color:#633806;font-size:10px;padding:1px 5px;border-radius:4px;display:inline-block;margin-top:2px">{chance}% fit</span>'
            if row.get("is_captain"):
                return '<span style="background:#E6F1FB;color:#0C447C;font-size:10px;padding:1px 5px;border-radius:4px;display:inline-block;margin-top:2px">© Captain</span>'
            return ""

        def card_border(row):
            if row["status"] == "i":  return "border:1.5px solid #E24B4A"
            if row["status"] == "d":  return "border:1.5px solid #EF9F27"
            if row.get("is_captain"): return "border:1.5px solid #185FA5"
            return "border:0.5px solid rgba(255,255,255,0.3)"

        def player_card_html(row, opacity=1.0):
            return (
                f'<div style="background:var(--color-background-primary);'
                f'{card_border(row)};border-radius:8px;padding:6px 8px;'
                f'text-align:center;min-width:80px;max-width:95px;'
                f'flex:1;opacity:{opacity}">'
                f'<p style="font-size:11px;font-weight:500;margin:0;'
                f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'
                f'color:var(--color-text-primary)">{row["name"]}</p>'
                f'<p style="font-size:10px;color:var(--color-text-secondary);'
                f'margin:1px 0 0">£{row["price"]}m</p>'
                f'<p style="font-size:11px;margin:3px 0 0;{ep_color(row["ep_next"])}">'
                f'EP: {row["ep_next"]}</p>'
                f'{status_badge(row)}'
                f'</div>'
            )

        def render_row(players, label):
            if players.empty:
                return
            cards = "".join(
                player_card_html(row) for _, row in players.iterrows()
            )
            st.markdown(
                f'<p style="font-size:10px;color:rgba(255,255,255,0.5);'
                f'text-align:center;margin:6px 0 4px;letter-spacing:0.05em">'
                f'{label}</p>'
                f'<div style="display:flex;justify-content:center;'
                f'gap:6px;margin-bottom:4px;flex-wrap:nowrap">{cards}</div>',
                unsafe_allow_html=True
            )

        # FPL pick_position: 1-11 = starters, 12-15 = bench
        # Sort by pick_position to respect manager's chosen order
        squad_sorted = squad.sort_values("pick_position")

        starters = squad_sorted[squad_sorted["pick_position"] <= 11]
        bench    = squad_sorted[squad_sorted["pick_position"] > 11]

        # Split starters by position
        gks  = starters[starters["position"] == "GK"]
        defs = starters[starters["position"] == "DEF"]
        mids = starters[starters["position"] == "MID"]
        fwds = starters[starters["position"] == "FWD"]

        # Pitch
        st.markdown(
            '<div style="background:#2d7a3a;border-radius:12px;'
            'padding:12px 8px;">',
            unsafe_allow_html=True
        )

        render_row(fwds, "FORWARDS")
        render_row(mids, "MIDFIELDERS")
        render_row(defs, "DEFENDERS")
        render_row(gks,  "GOALKEEPER")

        # Bench
        st.markdown(
            '<hr style="border:0;border-top:1.5px dashed rgba(255,255,255,0.2);'
            'margin:10px 0 6px">'
            '<p style="font-size:10px;color:rgba(255,255,255,0.4);'
            'text-align:center;margin:0 0 4px">BENCH</p>',
            unsafe_allow_html=True
        )

        bench_cards = "".join(
            player_card_html(row, opacity=0.65)
            for _, row in bench.iterrows()
        )
        st.markdown(
            f'<div style="display:flex;justify-content:center;'
            f'gap:6px;margin-bottom:4px">{bench_cards}</div>',
            unsafe_allow_html=True
        )

        # Legend
        st.markdown(
            '<div style="display:flex;gap:16px;justify-content:center;'
            'margin-top:8px;flex-wrap:wrap;padding-bottom:4px">'
            '<span style="font-size:11px;color:var(--color-text-secondary);'
            'display:flex;align-items:center;gap:4px">'
            '<span style="display:inline-block;width:10px;height:10px;'
            'border-radius:2px;background:#E24B4A"></span>Injured</span>'
            '<span style="font-size:11px;color:var(--color-text-secondary);'
            'display:flex;align-items:center;gap:4px">'
            '<span style="display:inline-block;width:10px;height:10px;'
            'border-radius:2px;background:#EF9F27"></span>Doubtful</span>'
            '<span style="font-size:11px;color:var(--color-text-secondary);'
            'display:flex;align-items:center;gap:4px">'
            '<span style="display:inline-block;width:10px;height:10px;'
            'border-radius:2px;background:#185FA5"></span>Captain</span>'
            '<span style="font-size:11px;color:var(--color-text-secondary);'
            'display:flex;align-items:center;gap:4px">'
            '<span style="display:inline-block;width:10px;height:10px;'
            'border-radius:2px;background:#27500A"></span>EP 7+</span>'
            '</div>'
            '</div>',
            unsafe_allow_html=True
        )

    if not injured.empty or not doubtful.empty:
        st.subheader("🚨 Injury & Availability Alerts")
        for _, p in injured.iterrows():
            news = p.get("news", "") or "No details available"
            st.error(f"🔴 **{p['name']}** (£{p['price']}m) — "
                     f"Injured | 0% chance of playing | {news}")
        for _, p in doubtful.iterrows():
            chance = p.get("chance_of_playing_next_round")
            chance_str = f"{int(chance)}%" if pd.notna(chance) else "Unknown"
            news = p.get("news", "") or "No details available"
            st.warning(f"🟡 **{p['name']}** (£{p['price']}m) — "
                       f"Doubtful | {chance_str} chance | {news}")

    # --- Squad table ---
    with st.expander("👥 Your Current Squad", expanded=True):
        render_pitch_view(context["squad"])

        

    # --- AI Recommendation ---
    st.subheader("🤖 AI Transfer Recommendation")
    st.markdown(recommendation)