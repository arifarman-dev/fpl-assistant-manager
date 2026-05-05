import requests

# You must include your login cookies in the headers for this to work
headers = {
    "Cookie": "pl_profile=...; sessionid=..." 
}

team_id = "YOUR_TEAM_ID"
url = f"https://fantasy.premierleague.com/api/my-team/{team_id}/"

response = requests.get(url, headers=headers)
data = response.json()

free_transfers_limit = data['transfers']['limit']
transfers_made = data['transfers']['made']

# Free transfers available for the next deadline
available = free_transfers_limit - transfers_made
print(f"Available Free Transfers: {available}")