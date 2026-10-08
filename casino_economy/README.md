# Casino Economy Bot (Virtual Coins Only)

A Telegram game bot built with Python 3.11+, python-telegram-bot and SQLite. All chips are fictional: no deposits of real money, purchases, cash-outs, prizes, or monetary value.

## Features
- SQLite wallet, bank, transaction ledger, starting bonus and atomic transfers
- Daily/weekly rewards with duplicate-claim protection
- Coin flip, slots, dice, rock-paper-scissors, number guessing and lucky wheel
- Leaderboard, profile, transaction history and inline menu
- Admin grant/remove chips, account restriction and stats
- Per-command cooldowns, configurable bet limit, SQLite WAL and database constraints

## Setup (Termux / Linux / Windows)
1. Install Python 3.11 or newer.
2. Create a bot with Telegram's **@BotFather** and copy its token.
3. Copy `.env.example` to `.env`, then set `BOT_TOKEN` and your numeric Telegram ID in `ADMIN_IDS`.
4. Install and run:

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/Termux: source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

The bot reads environment variables directly. If using a `.env` file, export the values in your shell or add `from dotenv import load_dotenv; load_dotenv()` at the top of `bot.py` before importing `config`.

## Commands
`/start`, `/menu`, `/help`, `/balance`, `/profile`, `/daily`, `/weekly`, `/pay USER_ID AMOUNT`, `/history`, `/leaderboard`, `/flip AMOUNT`, `/slots AMOUNT`, `/dice AMOUNT`, `/rps rock|paper|scissors AMOUNT`, `/guess NUMBER AMOUNT`, `/wheel AMOUNT`, `/deposit AMOUNT`, `/withdraw AMOUNT`.

Admin commands: `/grant USER_ID AMOUNT`, `/removechips USER_ID AMOUNT`, `/ban USER_ID`, `/unban USER_ID`, `/stats`.

## Environment
See `.env.example`. Keep the bot token private and never commit your real `.env` file.

## Notes
This is a first functional baseline, not a claim that every feature in the original master specification is implemented. Scheduled lottery, multiplayer challenges, blackjack/mines state machines, automated backup/export, migrations and a comprehensive automated test suite remain to be added before calling it fully production-ready.
