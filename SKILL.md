---
name: market-arbitrage-monitor
description: Monitor Renaiss marketplace in real-time, comparing listings with PriceCharting/SNKRDUNK for arbitrage opportunities.
---

# Market Arbitrage Monitor 📈

This skill enables an AI agent to monitor the Renaiss marketplace and identify arbitrage opportunities by comparing current asking prices with historical averages from PriceCharting and SNKRDUNK.

## Prerequisites & Setup
Before usage, the environment **MUST** be configured via a `.env` file (see `.env.example`):

1. **Discord Setup**: `DISCORD_WEBHOOK_URL` is required for alerts.
2. **Thresholds**: 
   - `WINDOW_DAYS` (Default: 30): Rolling window for average price calculation.
   - `PRICE_THRESHOLD` (Default: 20.0): Price difference (USD) to trigger an alert.
3. **AI Vision (Optional)**: Set `MINIMAX_API_KEY` or `OPENAI_API_KEY` for card identification if titles are ambiguous.

### Quick Start
```bash
# 1. Initialize environment
cp .env.example .env

# 2. Install dependencies
pip install -r requirements.txt

# 3. Launch monitor
python3 market_monitor.py
```

## Agent Capabilities & Logic
- **Real-Time Analysis**: Direct scraping of PC and SNKR using Jina/BeautifulSoup.
- **Incremental Scanning**: Tracks `SEEN_IDS` in memory; only analyzes genuine **NEW** listings to save API calls.
- **30-Day Filtering**: Robust date parsing ensures averages reflect current market heat.
- **Independent Alerts**: Triggers if **either** source shows a significant price gap.

## Interaction Patterns
- **Adjusting Rules**: Suggest the user to update `.env` or edit the "Manual Configuration" block in `market_monitor.py`.
- **Status Checks**: Run `tail -f market_monitor.log` to observe real-time scanning activity.
- **Troubleshooting**: If no prices are found, verify if the card title needs clarification via the Vision API.
