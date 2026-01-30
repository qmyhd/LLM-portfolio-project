# 🚀 Bot Startup & Testing Guide

This guide walks you through starting the bot, backfilling data, and verifying everything is working.

## 1. Start the Bot

Open your terminal (PowerShell) and run:

```powershell
python -m src.bot.bot
```cd "C:\Users\qaism\OneDrive\Documents\Github\llm-portfolio\scripts"

You should see: `✅ Bot is online and logged in as ...`

## 2. Data Collection (Discord & SnapTrade)

Once the bot is running, go to your Discord server and run these commands in a monitored channel.

### 📥 Step A: Collect SnapTrade Data (Brokerage)
Fetch all available positions, orders, and balances.

**Command:**
```
!fetch all
```
*Wait for the "Sync Complete" message.*

### 📥 Step B: Backfill Discord History
Collect historical trading picks and messages. This runs in the background.

**Command (for trading channels):**
```
!backfill trading
```
*This will fetch all history, clean it, extract tickers, and save it to `discord_trading_clean`.*

**Command (for general market chat):**
```
!backfill market
```

## 3. Testing Commands

Verify the bot's features are working.

| Feature | Command | Expected Output |
|---------|---------|-----------------|
| **Portfolio** | `!portfolio` | Interactive embed showing your current holdings and P/L. |
| **Charts** | `!chart AAPL` | A price chart with your buy/sell markers overlaid. |
| **Analysis** | `!position NVDA` | Detailed text report of your performance with that stock. |

## 4. System Verification

Run this script to check if data is successfully saving to the database:

```powershell
python scripts/check_system_status.py
```

**What to look for:**
- **COUNT**: Should be > 0 for all tables.
- **LATEST ENTRY**: Should show today's date/time after you run `!fetch all` or `!backfill`.

| **Twitter** | `!twitter TSLA` | Recent tweets and sentiment about the stock. |
| **EOD Data** | `!EOD` | Interactive prompt to get end-of-day price data. |

## 4. Verify System Status

To confirm data is actually being saved to Supabase, run this script in a **new terminal window** (keep the bot running in the first one):

```powershell
python scripts/check_system_status.py
```

**What to look for:**
1.  **`positions` count > 0**: Confirms SnapTrade sync worked.
2.  **`discord_messages` count**: Should increase as `!backfill` runs.
3.  **`discord_trading_clean` count**: Should increase as messages are processed.

## 5. Troubleshooting

*   **Bot doesn't reply?** Check the terminal for error logs.
*   **SnapTrade errors?** Check `!status` to see connection health.
