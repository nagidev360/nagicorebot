"""SQLite persistence with atomic balance changes and an audit ledger."""
import sqlite3
import time
import uuid
from contextlib import contextmanager
from config import DB_PATH, STARTING_BALANCE

def connect():
    con = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=15000")
    return con

def init_db():
    with connect() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0),
            bank INTEGER NOT NULL DEFAULT 0 CHECK(bank >= 0), xp INTEGER NOT NULL DEFAULT 0,
            level INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL,
            last_daily INTEGER NOT NULL DEFAULT 0, last_weekly INTEGER NOT NULL DEFAULT 0,
            daily_streak INTEGER NOT NULL DEFAULT 0, banned INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS transactions(
            id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, delta INTEGER NOT NULL,
            balance_after INTEGER NOT NULL, reason TEXT NOT NULL, created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_transactions_user_time ON transactions(user_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS cooldowns(user_id INTEGER NOT NULL, command TEXT NOT NULL, used_at INTEGER NOT NULL,
            PRIMARY KEY(user_id, command));
        """)

def ensure_user(user_id, username=None):
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row is None:
            con.execute("INSERT INTO users(user_id, username, balance, created_at) VALUES(?,?,?,?)",
                        (user_id, username, STARTING_BALANCE, int(time.time())))
            con.execute("INSERT INTO transactions VALUES(?,?,?,?,?,?)",
                        (uuid.uuid4().hex, user_id, STARTING_BALANCE, STARTING_BALANCE, "starting bonus", int(time.time())))
        elif username:
            con.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
        con.commit()

def get_user(user_id):
    with connect() as con:
        return con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

def change_balance(user_id, delta, reason):
    """Atomically apply delta; negative balances are rejected."""
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row is None:
            con.rollback()
            raise ValueError("User has not started the bot yet.")
        new_balance = row["balance"] + int(delta)
        if new_balance < 0:
            con.rollback()
            raise ValueError("Insufficient balance.")
        con.execute("UPDATE users SET balance=?, xp=xp+? WHERE user_id=?", (new_balance, max(0, abs(int(delta)) // 10), user_id))
        con.execute("INSERT INTO transactions VALUES(?,?,?,?,?,?)",
                    (uuid.uuid4().hex, user_id, int(delta), new_balance, reason[:120], int(time.time())))
        con.commit()
        return new_balance

def transfer(sender, recipient, amount):
    if sender == recipient:
        raise ValueError("You cannot pay yourself.")
    if amount <= 0:
        raise ValueError("Amount must be positive.")
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        users = con.execute("SELECT user_id,balance FROM users WHERE user_id IN (?,?)", (sender, recipient)).fetchall()
        balances = {r["user_id"]: r["balance"] for r in users}
        if sender not in balances or recipient not in balances:
            con.rollback()
            raise ValueError("Both users must start the bot before transfers.")
        if balances[sender] < amount:
            con.rollback()
            raise ValueError("Insufficient balance.")
        now = int(time.time())
        for uid, delta, reason in ((sender, -amount, f"transfer to {recipient}"), (recipient, amount, f"transfer from {sender}")):
            new = balances[uid] + delta
            con.execute("UPDATE users SET balance=? WHERE user_id=?", (new, uid))
            con.execute("INSERT INTO transactions VALUES(?,?,?,?,?,?)",
                        (uuid.uuid4().hex, uid, delta, new, reason, now))
        con.commit()
        return balances[sender] - amount, balances[recipient] + amount

def claim_reward(user_id, kind, amount, period):
    column = "last_daily" if kind == "daily" else "last_weekly"
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(f"SELECT balance,{column} AS last FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row is None:
            con.rollback()
            raise ValueError("Send /start first.")
        now = int(time.time())
        remaining = period - (now - row["last"])
        if remaining > 0:
            con.rollback()
            return False, remaining, row["balance"]
        new_balance = row["balance"] + amount
        con.execute(f"UPDATE users SET balance=?,{column}=? WHERE user_id=?", (new_balance, now, user_id))
        con.execute("INSERT INTO transactions VALUES(?,?,?,?,?,?)",
                    (uuid.uuid4().hex, user_id, amount, new_balance, f"{kind} reward", now))
        con.commit()
        return True, 0, new_balance

def history(user_id, limit=10):
    with connect() as con:
        return con.execute("SELECT delta,balance_after,reason,created_at FROM transactions WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                           (user_id, limit)).fetchall()

def leaderboard(limit=10):
    with connect() as con:
        return con.execute("SELECT user_id,username,balance,level,xp FROM users WHERE banned=0 ORDER BY balance DESC LIMIT ?", (limit,)).fetchall()

def cooldown_ok(user_id, command, seconds):
    now = int(time.time())
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT used_at FROM cooldowns WHERE user_id=? AND command=?", (user_id, command)).fetchone()
        if row and now - row["used_at"] < seconds:
            con.rollback()
            return False, seconds - (now - row["used_at"])
        con.execute("INSERT INTO cooldowns VALUES(?,?,?) ON CONFLICT(user_id,command) DO UPDATE SET used_at=excluded.used_at",
                    (user_id, command, now))
        con.commit()
        return True, 0

def set_banned(user_id, value):
    with connect() as con:
        con.execute("UPDATE users SET banned=? WHERE user_id=?", (int(value), user_id))

def admin_adjust(user_id, delta, reason):
    return change_balance(user_id, delta, f"admin: {reason}")
