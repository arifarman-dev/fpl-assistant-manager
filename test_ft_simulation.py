# test_ft_simulation.py
import requests

headers = {"User-Agent": "Mozilla/5.0"}
BASE = "https://fantasy.premierleague.com/api"
team_id = 81578

history = requests.get(
    f"{BASE}/entry/{team_id}/history/",
    headers=headers
).json()

gw_history = sorted(history["current"], key=lambda x: x["event"])
chips_used = {c["event"]: c["name"] for c in history.get("chips", [])}

print(f"{'GW':<5} {'Chip':<12} {'Made':<6} {'Cost':<6} {'FT Bank (start)'}")
print("-" * 50)

ft_bank = 1
for gw in gw_history:
    gw_num = gw["event"]
    made   = gw["event_transfers"]
    cost   = gw["event_transfers_cost"]
    chip   = chips_used.get(gw_num, "")

    print(f"GW{gw_num:<3} {chip:<12} {made:<6} {cost:<6} {ft_bank}")

    if chip == "freehit":
        ft_bank = ft_bank + 1
    elif chip == "wildcard":
        ft_bank = 1 + 1
    elif cost > 0:
        ft_bank = 1 + 1
    else:
        ft_bank = max(0, ft_bank - made) + 1

print(f"\nCalculated FT for next GW: {ft_bank}")
print(f"Actual FT shown in FPL:    3")

ft_capped = min(max(1, ft_bank), 3)
print(f"Calculated FT (capped at 3): {ft_capped}")
print(f"Actual FT shown in FPL:      3")