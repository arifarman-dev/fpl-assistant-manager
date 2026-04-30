# test_llm_connection.py
import requests
from config import OPENROUTER_API_KEY, MODEL

def test_openrouter():
    print(f"Testing OpenRouter connection with {MODEL}...\n")

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You are an FPL transfer recommendation assistant."
            },
            {
                "role": "user",
                "content": (
                    "Here is a test. I have Mohamed Salah in my team at £14.0m, "
                    "form 6.3, ep_next 4.7, upcoming fixtures: 4 / 3 / 4. "
                    "Should I keep or sell him? Give a one sentence answer."
                )
            }
        ],
        "max_tokens": 2000
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
    }

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=30
        )
        response.raise_for_status()
        data = response.json()

        content = data["choices"][0]["message"]["content"]
        model_used = data.get("model", "unknown")
        tokens_used = data.get("usage", {})

        print(f"✅ Connection successful")
        print(f"   Model:        {model_used}")
        print(f"   Tokens used:  {tokens_used}")
        print(f"\n   Response: {content}")

    except requests.exceptions.Timeout:
        print("❌ Request timed out — OpenRouter may be slow, try again")
    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP error: {e.response.status_code} — {e.response.text}")
    except KeyError:
        print(f"❌ Unexpected response structure: {data}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

if __name__ == "__main__":
    test_openrouter()