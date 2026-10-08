"""Telegram virtual-coin games bot. No deposits, withdrawals, or real-money play."""
import logging
import time
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()  # Load local .env before importing config.

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import config
import database as db
import games

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("casino-economy")

def money(n):
    return f"{n:,} chips"

def active_user(update):
    u = update.effective_user
    return u and db.get_user(u.id)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.ensure_user(u.id, u.username or u.first_name)
    await update.effective_message.reply_text(
        f"🎰 Welcome, {u.first_name}!\nYour virtual wallet is ready.\n\n"
        f"Starting bonus: {money(config.STARTING_BALANCE)}\n"
        "Coins are fictional and cannot be bought, sold, or withdrawn.\n\nUse /menu to play.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎮 Games", callback_data="menu_games"),
                                           InlineKeyboardButton("👛 Wallet", callback_data="menu_wallet")]]))

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "/start — create wallet\n/menu — game menu\n/balance — wallet\n/profile — profile\n"
        "/daily and /weekly — rewards\n/pay USER_ID AMOUNT — transfer chips\n/history — transactions\n"
        "/leaderboard — top players\n/games — game commands\n"
        "/flip AMOUNT — coin flip (random side)\n/slots AMOUNT — slots\n/dice AMOUNT — dice\n"
        "/rps rock|paper|scissors AMOUNT — RPS\n/guess NUMBER AMOUNT — guess 1–10\n/wheel AMOUNT — lucky wheel\n"
        "/deposit AMOUNT or /withdraw AMOUNT — move chips between wallet and bank\n\n"
        "Virtual chips only. No real-money gambling or payouts.")

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("👛 Wallet", callback_data="menu_wallet"),
           InlineKeyboardButton("🎮 Games", callback_data="menu_games")],
          [InlineKeyboardButton("🎁 Daily reward", callback_data="menu_daily"),
           InlineKeyboardButton("🏆 Leaderboard", callback_data="menu_leaderboard")]]
    await update.effective_message.reply_text("🎰 Casino Economy\nChoose an option:", reply_markup=InlineKeyboardMarkup(kb))

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if not db.get_user(uid):
        db.ensure_user(uid, q.from_user.username or q.from_user.first_name)
    if q.data == "menu_wallet":
        row = db.get_user(uid)
        msg = f"👛 Wallet: {money(row['balance'])}\n🏦 Bank: {money(row['bank'])}\n⭐ Level: {row['level']} · XP: {row['xp']}"
    elif q.data == "menu_games":
        msg = "🎮 Games: /flip AMOUNT, /slots AMOUNT, /dice AMOUNT, /rps CHOICE AMOUNT, /guess NUMBER AMOUNT, /wheel AMOUNT"
    elif q.data == "menu_daily":
        ok, remain, bal = db.claim_reward(uid, "daily", config.DAILY_REWARD, 86400)
        msg = f"🎁 Reward claimed: {money(config.DAILY_REWARD)}. Balance: {money(bal)}" if ok else f"Come back in {timedelta(seconds=remain)}."
    else:
        rows = db.leaderboard(10)
        msg = "🏆 Top players\n" + ("\n".join(f"{i}. {r['username'] or r['user_id']} — {money(r['balance'])}" for i, r in enumerate(rows, 1)) or "No players yet.")
    await q.edit_message_text(msg)

async def require_user(update, command):
    u = update.effective_user
    row = db.get_user(u.id)
    if not row:
        await update.effective_message.reply_text("Send /start first to create your wallet.")
        return None
    if row["banned"]:
        await update.effective_message.reply_text("Your casino account is restricted.")
        return None
    ok, wait = db.cooldown_ok(u.id, command, config.COOLDOWN_SECONDS)
    if not ok:
        await update.effective_message.reply_text(f"Slow down. Try again in {wait}s.")
        return None
    return row

async def balance(update, context):
    row = await require_user(update, "balance")
    if row:
        await update.effective_message.reply_text(f"👛 Wallet: {money(row['balance'])}\n🏦 Bank: {money(row['bank'])}\n⭐ Level: {row['level']} · XP: {row['xp']}")

async def profile(update, context):
    row = await require_user(update, "profile")
    if row:
        u = update.effective_user
        await update.effective_message.reply_text(f"👤 {u.full_name}\nID: {u.id}\nLevel: {row['level']}\nXP: {row['xp']}\nBalance: {money(row['balance'])}\nJoined: {time.strftime('%Y-%m-%d', time.gmtime(row['created_at']))}")

async def reward(update, context, kind):
    row = await require_user(update, kind)
    if not row: return
    amount, period = (config.DAILY_REWARD, 86400) if kind == "daily" else (config.WEEKLY_REWARD, 604800)
    ok, remain, bal = db.claim_reward(update.effective_user.id, kind, amount, period)
    await update.effective_message.reply_text(f"🎁 You received {money(amount)}! Balance: {money(bal)}" if ok else f"Already claimed. Try again in {timedelta(seconds=remain)}.")

async def daily(update, context): await reward(update, context, "daily")
async def weekly(update, context): await reward(update, context, "weekly")

async def pay(update, context):
    row = await require_user(update, "pay")
    if not row: return
    if len(context.args) != 2:
        await update.effective_message.reply_text("Usage: /pay USER_ID AMOUNT"); return
    try:
        recipient, amount = int(context.args[0]), int(context.args[1])
        if amount <= 0 or amount > config.MAX_BET: raise ValueError("Amount must be between 1 and the configured limit.")
        a, b = db.transfer(update.effective_user.id, recipient, amount)
        await update.effective_message.reply_text(f"Transfer complete: {money(amount)}. Your balance: {money(a)}.")
        try: await context.bot.send_message(recipient, f"You received {money(amount)} from {update.effective_user.full_name}. Balance: {money(b)}.")
        except Exception: pass
    except (ValueError, TypeError) as e: await update.effective_message.reply_text(str(e))

async def history_cmd(update, context):
    row = await require_user(update, "history")
    if not row: return
    rows = db.history(update.effective_user.id)
    if not rows:
        await update.effective_message.reply_text("No transactions yet."); return
    lines = [f"{'+' if r['delta'] >= 0 else ''}{money(r['delta'])} · {r['reason']} · balance {money(r['balance_after'])}" for r in rows]
    await update.effective_message.reply_text("📜 Recent transactions\n" + "\n".join(lines))

async def leaderboard_cmd(update, context):
    if not await require_user(update, "leaderboard"): return
    rows = db.leaderboard(10)
    await update.effective_message.reply_text("🏆 Top players\n" + ("\n".join(f"{i}. {r['username'] or r['user_id']} — {money(r['balance'])}" for i, r in enumerate(rows, 1)) or "No players yet."))

async def game_start(update, command):
    row = await require_user(update, command)
    if not row: return None
    args = update.effective_message.text.split()[1:]
    if not args:
        await update.effective_message.reply_text(f"Usage: /{command} AMOUNT"); return None
    try: amount = int(args[-1])
    except ValueError:
        await update.effective_message.reply_text("Bet must be a whole number."); return None
    if amount < 1 or amount > config.MAX_BET:
        await update.effective_message.reply_text(f"Bet must be between 1 and {money(config.MAX_BET)}."); return None
    if row["balance"] < amount:
        await update.effective_message.reply_text("Insufficient wallet balance."); return None
    return amount

async def flip(update, context):
    amount = await game_start(update, "flip")
    if amount is None: return
    outcome = games.coinflip()
    win = outcome == "Heads"
    delta = amount if win else -amount
    try: bal = db.change_balance(update.effective_user.id, delta, f"coin flip: {outcome}")
    except ValueError as e: await update.effective_message.reply_text(str(e)); return
    await update.effective_message.reply_text(f"🪙 Result: {outcome}\n" + (f"You won {money(amount)}!" if win else f"You lost {money(amount)}.") + f"\nBalance: {money(bal)}")

async def slots(update, context):
    amount = await game_start(update, "slots")
    if amount is None: return
    result = games.slots()
    if result[0] == result[1] == result[2]: mult = 5
    elif len(set(result)) == 2: mult = 2
    else: mult = 0
    delta = amount * mult - amount
    bal = db.change_balance(update.effective_user.id, delta, "slots")
    await update.effective_message.reply_text(f"🎰 {' | '.join(result)}\n" + (f"Win: {money(amount*mult)}" if mult else f"Lost: {money(amount)}") + f"\nBalance: {money(bal)}")

async def dice_game(update, context):
    amount = await game_start(update, "dice")
    if amount is None: return
    result = games.dice()
    delta = amount if result >= 4 else -amount
    bal = db.change_balance(update.effective_user.id, delta, f"dice result {result}")
    await update.effective_message.reply_text(f"🎲 You rolled {result}. " + (f"You won {money(amount)}!" if delta > 0 else f"You lost {money(amount)}.") + f"\nBalance: {money(bal)}")

async def rps_game(update, context):
    row = await require_user(update, "rps")
    if not row: return
    args = context.args
    if len(args) != 2 or args[0].lower() not in ("rock","paper","scissors"):
        await update.effective_message.reply_text("Usage: /rps rock|paper|scissors AMOUNT"); return
    try: amount = int(args[1])
    except ValueError: await update.effective_message.reply_text("Invalid bet."); return
    if not 1 <= amount <= config.MAX_BET or row["balance"] < amount:
        await update.effective_message.reply_text("Bet is outside limits or your balance is too low."); return
    player, bot = args[0].lower(), games.rps()
    if player == bot: delta, result = 0, "Draw — bet returned."
    elif (player, bot) in (("rock","scissors"),("paper","rock"),("scissors","paper")): delta, result = amount, f"You win {money(amount)}!"
    else: delta, result = -amount, f"You lose {money(amount)}."
    bal = db.change_balance(update.effective_user.id, delta, f"RPS {player} vs {bot}")
    await update.effective_message.reply_text(f"You: {player} · Bot: {bot}\n{result}\nBalance: {money(bal)}")

async def guess(update, context):
    row = await require_user(update, "guess")
    if not row: return
    if len(context.args) != 2:
        await update.effective_message.reply_text("Usage: /guess NUMBER AMOUNT"); return
    try: choice, amount = int(context.args[0]), int(context.args[1])
    except ValueError: await update.effective_message.reply_text("Enter whole numbers."); return
    if not 1 <= choice <= 10 or not 1 <= amount <= config.MAX_BET or row["balance"] < amount:
        await update.effective_message.reply_text("Number must be 1–10 and bet must be within your balance/limit."); return
    answer = games.guess_number()
    delta = amount * 8 if choice == answer else -amount
    bal = db.change_balance(update.effective_user.id, delta, f"guess {choice}, answer {answer}")
    await update.effective_message.reply_text(f"🎯 Number: {answer}\n" + (f"Correct! Net win {money(amount*8)}." if delta > 0 else f"Not this time; lost {money(amount)}.") + f"\nBalance: {money(bal)}")

async def wheel_game(update, context):
    amount = await game_start(update, "wheel")
    if amount is None: return
    mult = games.wheel()
    delta = int(amount * mult) - amount
    bal = db.change_balance(update.effective_user.id, delta, f"lucky wheel multiplier {mult}x")
    await update.effective_message.reply_text(f"🎡 Multiplier: {mult}x\n" + (f"Net result: +{money(delta)}" if delta > 0 else f"Net result: {money(delta)}") + f"\nBalance: {money(bal)}")

async def bank_move(update, context, direction):
    row = await require_user(update, direction)
    if not row: return
    if len(context.args) != 1:
        await update.effective_message.reply_text(f"Usage: /{direction} AMOUNT"); return
    try: amount = int(context.args[0])
    except ValueError: await update.effective_message.reply_text("Amount must be a whole number."); return
    if amount <= 0: await update.effective_message.reply_text("Amount must be positive."); return
    with db.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        r = con.execute("SELECT balance,bank FROM users WHERE user_id=?", (update.effective_user.id,)).fetchone()
        source, dest = ("balance","bank") if direction == "deposit" else ("bank","balance")
        if r[source] < amount:
            con.rollback(); await update.effective_message.reply_text("Insufficient funds."); return
        con.execute(f"UPDATE users SET {source}={source}-?,{dest}={dest}+? WHERE user_id=?", (amount, amount, update.effective_user.id))
        con.execute("INSERT INTO transactions VALUES(?,?,?,?,?,?)", (__import__('uuid').uuid4().hex, update.effective_user.id, 0, r['balance'] + (amount if direction == 'withdraw' else -amount), f"{direction} {amount}", int(time.time())))
        con.commit()
    await update.effective_message.reply_text(f"{direction.title()} complete: {money(amount)}.")

async def deposit(update, context): await bank_move(update, context, "deposit")
async def withdraw(update, context): await bank_move(update, context, "withdraw")

async def admin_grant(update, context):
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("Admin only."); return
    if len(context.args) != 2:
        await update.effective_message.reply_text("Usage: /grant USER_ID AMOUNT"); return
    try:
        uid, amount = int(context.args[0]), int(context.args[1])
        if amount <= 0: raise ValueError("Amount must be positive.")
        db.ensure_user(uid)
        bal = db.admin_adjust(uid, amount, f"grant by {update.effective_user.id}")
        await update.effective_message.reply_text(f"Granted {money(amount)} to {uid}. New balance: {money(bal)}")
    except ValueError as e: await update.effective_message.reply_text(str(e))

async def admin_remove(update, context):
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("Admin only."); return
    if len(context.args) != 2:
        await update.effective_message.reply_text("Usage: /removechips USER_ID AMOUNT"); return
    try:
        uid, amount = int(context.args[0]), int(context.args[1])
        if amount <= 0: raise ValueError("Amount must be positive.")
        bal = db.admin_adjust(uid, -amount, f"remove by {update.effective_user.id}")
        await update.effective_message.reply_text(f"Removed chips. Balance: {money(bal)}")
    except ValueError as e: await update.effective_message.reply_text(str(e))

async def admin_ban(update, context):
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("Admin only."); return
    if len(context.args) != 1:
        await update.effective_message.reply_text("Usage: /ban USER_ID"); return
    try:
        uid = int(context.args[0])
        db.set_banned(uid, True)
        await update.effective_message.reply_text(f"Account {uid} restricted.")
    except ValueError: await update.effective_message.reply_text("Invalid user ID.")

async def admin_unban(update, context):
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("Admin only."); return
    if len(context.args) != 1:
        await update.effective_message.reply_text("Usage: /unban USER_ID"); return
    try:
        db.set_banned(int(context.args[0]), False)
        await update.effective_message.reply_text("Account unrestricted.")
    except ValueError: await update.effective_message.reply_text("Invalid user ID.")

async def stats(update, context):
    if update.effective_user.id not in config.ADMIN_IDS:
        await update.effective_message.reply_text("Admin only."); return
    with db.connect() as con:
        users = con.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        supply = con.execute("SELECT COALESCE(SUM(balance+bank),0) n FROM users").fetchone()["n"]
    await update.effective_message.reply_text(f"Users: {users}\nTotal virtual chips: {money(supply)}")

def main():
    if not config.BOT_TOKEN:
        raise SystemExit("Set BOT_TOKEN in your environment or .env file.")
    db.init_db()
    app = Application.builder().token(config.BOT_TOKEN).build()
    for name, fn in [
        ("start", start), ("help", help_cmd), ("menu", menu), ("balance", balance), ("profile", profile),
        ("daily", daily), ("weekly", weekly), ("pay", pay), ("history", history_cmd), ("leaderboard", leaderboard_cmd),
        ("flip", flip), ("slots", slots), ("dice", dice_game), ("rps", rps_game), ("guess", guess), ("wheel", wheel_game),
        ("deposit", deposit), ("withdraw", withdraw), ("grant", admin_grant), ("removechips", admin_remove),
        ("ban", admin_ban), ("unban", admin_unban), ("stats", stats)
    ]: app.add_handler(CommandHandler(name, fn))
    app.add_handler(CommandHandler("games", help_cmd))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^menu_"))
    log.info("Casino Economy Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
