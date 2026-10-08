"""Pure game outcomes. Currency is fictional and has no cash value."""
import secrets

def coinflip():
    return secrets.choice(("Heads", "Tails"))

def slots():
    symbols = ["🍒", "🍋", "🔔", "⭐", "7️⃣"]
    return [secrets.choice(symbols) for _ in range(3)]

def dice():
    return secrets.randbelow(6) + 1

def rps():
    return secrets.choice(("rock", "paper", "scissors"))

def guess_number():
    return secrets.randbelow(10) + 1

def wheel():
    return secrets.choice([0, 0, 0.5, 1, 1.5, 2, 3, 5])
