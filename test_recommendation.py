# test_recommendation_v2.py
from fetcher import fetch_all
from transformer import build_recommendation_context
from data_enricher import enrich_context
from llm import get_recommendation

print("=== FPL Transfer Recommender — Enriched Pipeline Test ===\n")

data = fetch_all(81578)

context = build_recommendation_context(
    team_info=data["team_info"],
    picks=data["picks"],
    bootstrap=data["bootstrap"],
    fixtures=data["fixtures"]
)

print("Enriching with xG, Elo, and availability data...")
context = enrich_context(context, data["current_gw"])

# Preview enriched squad
print("\n=== Enriched Squad ===")
cols = ["name", "position", "price", "form", "ep_next",
        "chance_of_playing_next_round", "expected_goals_per_90",
        "expected_assists_per_90", "news"]
available = [c for c in cols if c in context["squad"].columns]
print(context["squad"][available].to_string(index=False))

print("\nGenerating enriched recommendation...")
recommendation = get_recommendation(context)
print("\n=== RECOMMENDATION ===")
print(recommendation)