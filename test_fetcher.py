from fetcher import fetch_all

data = fetch_all(81578)

print(f"\nCurrent GW:    {data['current_gw']}")
print(f"Manager:       {data['team_info']['player_first_name']} {data['team_info']['player_last_name']}")
print(f"Total players: {len(data['bootstrap']['elements'])}")
print(f"Squad size:    {len(data['picks']['picks'])}")
print(f"Total fix:     {len(data['fixtures'])}")