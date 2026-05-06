# FPL Assistant Manager

An AI-powered Fantasy Premier League transfer recommendation tool.

## Features
- **Transfer Hub** — AI transfer recommendations personalised to your squad,
  with season-long DGW/BGW planning and chip strategy
- **Transfer Planner** — Plan multiple transfers with live budget, 
  hit cost, and EP comparison
- **Differential Finder** — High-form, low-ownership players 
  the top managers are quietly targeting
- **GW Projections** — Bookmaker-implied projected goals and 
  clean sheet probabilities for the upcoming gameweek

## Data Sources
- [FPL Official API](https://fantasy.premierleague.com/api/) — 
  live player, fixture, and team data
- [FPL Core Insights](https://github.com/olbauday/FPL-Core-Insights) — 
  xG, xA, Elo ratings, and enhanced player stats
- [The Odds API](https://the-odds-api.com/) — 
  bookmaker-implied match probabilities
- [OpenRouter](https://openrouter.ai/) — 
  LLM reasoning via Gemini 2.5 Flash

## Setup

1. Clone the repository
2. Install dependencies:
   pip install -r requirements.txt
3. Copy .env.example to .env and add your API keys:
   OPENROUTER_API_KEY=your-key-here
   ODDS_API_KEY=your-key-here
4. Run the app:
   streamlit run app.py

## Architecture