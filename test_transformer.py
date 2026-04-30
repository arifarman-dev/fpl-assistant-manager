from fetcher import fetch_all
from transformer import build_recommendation_context

data = fetch_all(81578)

context = build_recommendation_context(
    team_info=data["team_info"],
    picks=data["picks"],
    bootstrap=data["bootstrap"],
    fixtures=data["fixtures"]
)

print(f"Manager:  {context['manager']}")
print(f"Team:     {context['team_name']}")
print(f"Bank:     £{context['bank']}m\n")

print("=== Current Squad ===")
cols = ["name", "position", "price", "form", "ep_next", "fdrs", "status", "is_captain"]
print(context["squad"][cols].to_string(index=False))

print("\n=== Top Transfer Candidates by Position ===")
for pos, df in context["candidates"].items():
    print(f"\n{pos}:")
    print(df[["name", "team", "price", "form", "ep_next", "fdrs", "score"]].to_string(index=False))