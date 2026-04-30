from fetcher import fetch_all
from transformer import build_recommendation_context
from llm import get_recommendation

print("=== FPL Transfer Recommender — Full Pipeline Test ===\n")

data = fetch_all(81578)

context = build_recommendation_context(
    team_info=data["team_info"],
    picks=data["picks"],
    bootstrap=data["bootstrap"],
    fixtures=data["fixtures"]
)

print("Generating recommendation...\n")
recommendation = get_recommendation(context)

print("=== RECOMMENDATION ===")
print(recommendation)