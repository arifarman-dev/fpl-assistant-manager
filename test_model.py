# test_model.py
import requests
from config import OPENROUTER_API_KEY, MODEL

print(f"Testing model: {MODEL}")

response = requests.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers={
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
    },
    json={
        "model": MODEL,
        "messages": [{"role": "user", "content": "Say hello in one word."}],
        "max_tokens": 10
    }
)

print(f"Status: {response.status_code}")
print(f"Response: {response.text}")