import asyncio
import logging
import os
import re
import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    MessageHandler, filters
)

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("nagicorebot")

TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_NAME = os.getenv("BOT_NAME", "NagiCoreBot")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
MAX_MB = int(os.getenv("MAX_DOWNLOAD_MB", "50"))
DOWNLOAD_TTL = int(os.getenv("DOWNLOAD_TTL_MINUTES", "10"))
DB = Path("nagicorebot.db")
WORK = Path("downloads")
WORK.mkdir(exist_ok=True)

URL_RE = re.compile(r"https?://\S+", re.I)
MEDIA_DOMAINS = ("youtube.com", "youtu.be", "instagram.com")

db = sqlite3.connect(DB, check_same_thread=False)
db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, username TEXT, joined INTEGER)")
db.execute("""CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY, title TEXT, rules TEXT DEFAULT 'No rules configured.',
    welcome INTEGER DEFAULT 1, antilink INTEGER DEFAULT 0, antispam INTEGER DEFAULT 1
)""")
db.execute("CREATE TABLE IF NOT EXISTS warnings (chat_id INTEGER, user_id INTEGER, count INTEGER, PRIMARY KEY(chat_id,user_id))")
db.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, chat_id INTEGER, source TEXT, mode TEXT, status TEXT, created INTEGER)")
db.commit()
db_lock = asyncio.Lock()

spam_cache = {}
url_jobs = {}

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def remember_user(user):
    db.execute(
        "INSERT INTO users(id,name,username,joined) VALUES(?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, username=excluded.username",
        (user.id, user.full_name[:120], user.username or "", int(time.time()))
    )
    db.commit()

def ensure_group(chat):
    db.execute("INSERT OR IGNORE INTO groups(id,title) VALUES(?,?)", (chat.id, chat.title or "Group"))
    db.execute("UPDATE groups SET title=? WHERE id=?", (chat.title or "Group", chat.id))
    db.commit()

def group_row(chat_id):
    db.execute("INSERT OR IGNORE INTO groups(id,title) VALUES(?,?)", (chat_id, "Group"))
    db.commit()
    return db.execute("SELECT * FROM groups WHERE id=?", (chat_id,)).fetchone()

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Downloader", callback_data="media"),
         InlineKeyboardButton("🔄 Converter", callback_data="convert")],
        [InlineKeyboardButton("📜 History", callback_data="history"),
         InlineKeyboardButton("👤 Profile", callback_data="profile")],
        [InlineKeyboardButton("📊 Stats", callback_data="stats"),
         InlineKeyboardButton("❓ Help", callback_data="help")]
    ])

def help_text():
    return (
        f"🤖 {BOT_NAME}\n\n"
        "DM:\n/start /menu /help /profile /id /stats /history /convert\n\n"
        "Group:\n/setup /rules /welcome /antispam /antilink /warn /mute /unmute "
        "/kick /ban /unban /groupinfo /id /ping\n\n"
        "🎬 Send a permitted YouTube or Instagram URL to get MP4/MP3 options.\n"
        "📁 Send a video/audio file and use /convert for conversion."
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    remember_user(user)
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.message.reply_text(
            f"👋 Welcome, {user.first_name}!\n\n{BOT_NAME} is ready.\n"
            "Send a supported media URL or choose an option below.",
            reply_markup=menu()
        )
    else:
        ensure_group(update.effective_chat)
        await update.message.reply_text(
            f"👋 Hello {user.first_name}. Use /setup to configure this group."
        )

async def menu_cmd(update, context):
    await update.message.reply_text("Main Menu", reply_markup=menu())

async def help_cmd(update, context):
    await update.message.reply_text(help_text())

async def id_cmd(update, context):
    u, c = update.effective_user, update.effective_chat
    await update.message.reply_text(f"👤 User ID: {u.id}\n💬 Chat ID: {c.id}")

async def profile_cmd(update, context):
    u = update.effective_user
    remember_user(u)
    await update.message.reply_text(
        f"👤 Profile\nName: {u.full_name}\nUsername: @{u.username or 'none'}\nID: {u.id}"
    )

async def stats_cmd(update, context):
    users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    groups = db.execute("SELECT COUNT(*) FROM groups").fetchone()[0]
    await update.message.reply_text(f"📊 Bot Statistics\nUsers: {users}\nGroups: {groups}")

async def ping_cmd(update, context):
    await update.message.reply_text("🏓 Pong!")

async def setup_cmd(update, context):
    if update.effective_chat.type == ChatType.PRIVATE:
        return await update.message.reply_text("Use /setup inside a group.")
    if not await require_group_admin(update):
        return
    ensure_group(update.effective_chat)
    await update.message.reply_text(
        "⚙️ Group configured.\n\n"
        "Commands:\n/antilink on|off\n/antispam on|off\n/welcome on|off"
    )

async def require_group_admin(update):
    member = await update.effective_chat.get_member(update.effective_user.id)
    if member.status not in ("administrator", "creator") and not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Group admin permission required.")
        return False
    return True

async def rules_cmd(update, context):
    if update.effective_chat.type == ChatType.PRIVATE:
        return await update.message.reply_text("Rules are available in groups.")
    row = group_row(update.effective_chat.id)
    await update.message.reply_text(f"📜 Group Rules\n\n{row[2]}")

async def toggle_cmd(update, context, field):
    if update.effective_chat.type == ChatType.PRIVATE or not await require_group_admin(update):
        return
    value = (context.args[0].lower() == "on") if context.args else None
    if value is None:
        return await update.message.reply_text("Usage: /" + field + " on|off")
    ensure_group(update.effective_chat)
    db.execute(f"UPDATE groups SET {field}=? WHERE id=?", (int(value), update.effective_chat.id))
    db.commit()
    await update.message.reply_text(f"✅ {field} {'enabled' if value else 'disabled'}.")

async def antilink_cmd(update, context):
    await toggle_cmd(update, context, "antilink")

async def antispam_cmd(update, context):
    await toggle_cmd(update, context, "antispam")

async def welcome_cmd(update, context):
    await toggle_cmd(update, context, "welcome")

async def groupinfo_cmd(update, context):
    c = update.effective_chat
    await update.message.reply_text(f"👥 {c.title}\nID: {c.id}\nMembers: {await context.bot.get_chat_member_count(c.id)}")

async def warn_cmd(update, context):
    if not await require_group_admin(update) or not context.args:
        return await update.message.reply_text("Usage: /warn USER_ID")
    try: uid = int(context.args[0])
    except ValueError: return await update.message.reply_text("Invalid user ID.")
    row = db.execute("SELECT count FROM warnings WHERE chat_id=? AND user_id=?", (update.effective_chat.id, uid)).fetchone()
    count = (row[0] if row else 0) + 1
    db.execute("INSERT OR REPLACE INTO warnings(chat_id,user_id,count) VALUES(?,?,?)", (update.effective_chat.id, uid, count))
    db.commit()
    if count >= 3:
        try:
            from telegram import ChatPermissions
            await update.effective_chat.restrict_member(uid, ChatPermissions(can_send_messages=False), until_date=int(time.time()+3600))
            await update.message.reply_text(f"🚫 User {uid} reached 3 warnings and was muted for 1 hour.")
        except Exception:
            await update.message.reply_text(f"⚠️ User {uid} warned. Total: {count}/3. Auto-mute failed.")
    else:
        await update.message.reply_text(f"⚠️ User {uid} warned. Total: {count}/3.")

async def moderate(update, context, action):
    if not await require_group_admin(update) or not context.args:
        return await update.message.reply_text(f"Usage: /{action} USER_ID [seconds]")
    try: uid = int(context.args[0])
    except ValueError: return await update.message.reply_text("Invalid user ID.")
    try:
        if action == "mute":
            seconds = max(10, min(int(context.args[1]) if len(context.args) > 1 else 60, 86400))
            until = int(time.time()) + seconds
            from telegram import ChatPermissions
            await update.effective_chat.restrict_member(uid, ChatPermissions(can_send_messages=False), until_date=until)
        elif action == "unmute":
            from telegram import ChatPermissions
            await update.effective_chat.restrict_member(uid, ChatPermissions(can_send_messages=True))
        elif action == "kick":
            await update.effective_chat.ban_member(uid)
            await update.effective_chat.unban_member(uid)
        elif action == "ban":
            await update.effective_chat.ban_member(uid)
        elif action == "unban":
            await update.effective_chat.unban_member(uid)
        await update.message.reply_text(f"✅ {action.title()} applied to {uid}.")
    except Exception as e:
        log.warning("moderation failed: %s", e)
        await update.message.reply_text("❌ Telegram rejected the action. Check bot admin permissions.")

async def mute_cmd(u,c): await moderate(u,c,"mute")
async def unmute_cmd(u,c): await moderate(u,c,"unmute")
async def kick_cmd(u,c): await moderate(u,c,"kick")
async def ban_cmd(u,c): await moderate(u,c,"ban")
async def unban_cmd(u,c): await moderate(u,c,"unban")

def valid_media_url(url):
    try:
        host = urlparse(url).netloc.lower().split(":")[0]
        return any(host == d or host.endswith("." + d) for d in MEDIA_DOMAINS)
    except Exception:
        return False

async def download_media(url, mode, quality="best"):
    job = WORK / uuid.uuid4().hex
    job.mkdir()
    output = job / "%(title).80s.%(ext)s"
    import yt_dlp
    opts = {
        "outtmpl": str(output),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "max_filesize": MAX_MB * 1024 * 1024,
    }
    if mode == "mp3":
        opts.update({"format": "bestaudio/best", "postprocessors": [{
            "key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"
        }]})
    else:
        fmt = "bv*+ba/b"
        if quality == "720":
            fmt = "bv*[height<=720]+ba/b[height<=720]"
        elif quality == "480":
            fmt = "bv*[height<=480]+ba/b[height<=480]"
        opts.update({"format": fmt, "merge_output_format": "mp4"})
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).download([url]))
        files = [p for p in job.iterdir() if p.is_file()]
        if not files: raise RuntimeError("No media file returned.")
        return files[0], job
    except Exception:
        shutil.rmtree(job, ignore_errors=True)
        raise

async def media_buttons(url):
    token = uuid.uuid4().hex[:12]
    url_jobs[token] = (url, time.time())
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 MP4 Best", callback_data="dl|mp4|best|" + token)],
        [InlineKeyboardButton("🎬 MP4 720p", callback_data="dl|mp4|720|" + token),
         InlineKeyboardButton("🎬 MP4 480p", callback_data="dl|mp4|480|" + token)],
        [InlineKeyboardButton("🎵 MP3 192k", callback_data="dl|mp3|best|" + token)],
        [InlineKeyboardButton("❌ Cancel", callback_data="close")]
    ])

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    remember_user(update.effective_user)
    text = msg.text or ""
    urls = URL_RE.findall(text)
    for url in urls:
        clean = url.rstrip(").,]")
        if valid_media_url(clean):
            await msg.reply_text("🎬 Media detected. Choose output:", reply_markup=await media_buttons(clean))
            return
    if update.effective_chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        row = group_row(update.effective_chat.id)
        if row[4] and URL_RE.search(text):
            await msg.delete()
            return
        if row[5]:
            key = (update.effective_chat.id, update.effective_user.id)
            now = time.time()
            hits = [t for t in spam_cache.get(key, []) if now - t < 10]
            hits.append(now)
            spam_cache[key] = hits
            if len(hits) >= 7:
                try:
                    from telegram import ChatPermissions
                    await update.effective_chat.restrict_member(
                        update.effective_user.id,
                        ChatPermissions(can_send_messages=False),
                        until_date=int(now + 60)
                    )
                except Exception: pass
                await msg.reply_text("🛡️ Anti-spam: user muted for 60 seconds.")
                spam_cache[key] = []

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "close":
        return await q.edit_message_text("Closed.")
    if data == "help":
        return await q.edit_message_text(help_text(), reply_markup=menu())
    if data == "profile":
        u = q.from_user
        return await q.edit_message_text(f"👤 {u.full_name}\nID: {u.id}", reply_markup=menu())
    if data == "history":
        rows = db.execute("SELECT mode,status,source FROM history WHERE user_id=? ORDER BY id DESC LIMIT 8", (q.from_user.id,)).fetchall()
        if not rows:
            return await q.edit_message_text("📜 No history yet.", reply_markup=menu())
        body = "📜 Recent History\n\n" + "\n".join(
            f"• {m.upper()} — {st} — {src[:35]}" for m,st,src in rows
        )
        return await q.edit_message_text(body, reply_markup=menu())
    if data == "stats":
        users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        groups = db.execute("SELECT COUNT(*) FROM groups").fetchone()[0]
        return await q.edit_message_text(f"📊 Users: {users}\nGroups: {groups}", reply_markup=menu())
    if data in ("media", "convert"):
        return await q.edit_message_text(
            "🎬 Send a permitted YouTube/Instagram URL, or send a media file to convert.",
            reply_markup=menu()
        )
    if data.startswith("dl|"):
        _, mode, quality, token = data.split("|", 3)
        job_data = url_jobs.get(token)
        if not job_data or time.time() - job_data[1] > DOWNLOAD_TTL * 60:
            url_jobs.pop(token, None)
            return await q.message.reply_text("❌ This download button has expired. Send the URL again.")
        url = job_data[0]
        await q.edit_message_text("⏳ Processing media…")
        try:
            path, job = await download_media(url, mode, quality)
            size = path.stat().st_size
            if size > MAX_MB * 1024 * 1024:
                raise RuntimeError("File exceeds configured Telegram upload limit.")
            with path.open("rb") as f:
                if mode == "mp3":
                    await q.message.reply_audio(f, filename=path.name)
                else:
                    await q.message.reply_video(f, filename=path.name, supports_streaming=True)
            db.execute("INSERT INTO history(user_id,chat_id,source,mode,status,created) VALUES(?,?,?,?,?,?)",
                       (q.from_user.id, q.message.chat_id, url, mode, "success", int(time.time())))
            db.commit()
            shutil.rmtree(job, ignore_errors=True)
            url_jobs.pop(token, None)
        except Exception as e:
            log.warning("download error: %s", e)
            db.execute("INSERT INTO history(user_id,chat_id,source,mode,status,created) VALUES(?,?,?,?,?,?)",
                       (q.from_user.id, q.message.chat_id, url, mode, "failed", int(time.time())))
            db.commit()
            await q.message.reply_text(
                "❌ Download/conversion failed. The URL may be unavailable, restricted, "
                "unsupported, or larger than the configured limit."
            )
        return

async def convert_cmd(update, context):
    await update.message.reply_text(
        "🔄 Converter ready. Send a video/audio/document file, then choose MP3 or MP4."
    )

async def media_file_handler(update, context):
    msg = update.message
    if not msg or update.effective_chat.type != ChatType.PRIVATE:
        return
    media = msg.video or msg.audio or msg.document
    if not media:
        return
    if getattr(media, "file_size", 0) and media.file_size > MAX_MB * 1024 * 1024:
        return await msg.reply_text(f"❌ File is larger than {MAX_MB} MB.")
    file = await context.bot.get_file(media.file_id)
    job = WORK / uuid.uuid4().hex
    job.mkdir()
    src = job / ("input" + Path(getattr(media, "file_name", "") or ".bin").suffix)
    await file.download_to_drive(src)
    await msg.reply_text("🔄 File received. Choose output:", reply_markup=InlineKeyboardMarkup([[
        InlineKeyboardButton("🎵 MP3", callback_data="file|mp3|" + str(job)),
        InlineKeyboardButton("🎬 MP4", callback_data="file|mp4|" + str(job))
    ]]))

async def file_callback(update, context):
    q = update.callback_query
    if not q.data.startswith("file|"): return
    await q.answer()
    _, mode, jobstr = q.data.split("|", 2)
    job = Path(jobstr)
    srcs = [p for p in job.iterdir() if p.is_file()] if job.exists() else []
    if not srcs:
        return await q.message.reply_text("❌ Temporary file expired.")
    src = srcs[0]
    out = job / ("converted.mp3" if mode == "mp3" else "converted.mp4")
    import subprocess
    cmd = ["ffmpeg", "-y", "-i", str(src)]
    if mode == "mp3":
        cmd += ["-vn", "-codec:a", "libmp3lame", "-b:a", "192k", str(out)]
    else:
        cmd += ["-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart", str(out)]
    await q.edit_message_text("⏳ Converting…")
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, err = await proc.communicate()
        if proc.returncode != 0 or not out.exists(): raise RuntimeError(err.decode(errors="ignore")[-500:])
        with out.open("rb") as f:
            if mode == "mp3": await q.message.reply_audio(f, filename="converted.mp3")
            else: await q.message.reply_video(f, filename="converted.mp4")
    except Exception as e:
        log.warning("conversion error: %s", e)
        await q.message.reply_text("❌ Conversion failed. Check the media format and FFmpeg installation.")
    finally:
        shutil.rmtree(job, ignore_errors=True)

async def new_member(update, context):
    row = group_row(update.effective_chat.id)
    if not row[3]: return
    for member in update.message.new_chat_members:
        await update.message.reply_text(f"👋 Welcome {member.mention_html()}!", parse_mode="HTML")

async def admin_cmd(update, context):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Owner only.")
    await update.message.reply_text(
        "👑 Admin Panel\n\n"
        "/stats — bot statistics\n"
        "/broadcast MESSAGE — send to known users"
    )

async def broadcast_cmd(update, context):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Owner only.")
    text = " ".join(context.args).strip()
    if not text: return await update.message.reply_text("Usage: /broadcast MESSAGE")
    ids = [r[0] for r in db.execute("SELECT id FROM users").fetchall()]
    sent = 0
    for uid in ids:
        try:
            await context.bot.send_message(uid, text)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception: pass
    await update.message.reply_text(f"📢 Broadcast complete: {sent}/{len(ids)} sent.")

async def cleanup_loop():
    while True:
        cutoff = time.time() - DOWNLOAD_TTL * 60
        for p in WORK.iterdir():
            try:
                if p.stat().st_mtime < cutoff: shutil.rmtree(p, ignore_errors=True)
            except Exception: pass
        await asyncio.sleep(60)

async def post_init(app):
    asyncio.create_task(cleanup_loop())

def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Copy .env.example to .env and configure it.")
    app = Application.builder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("id", id_cmd))
    app.add_handler(CommandHandler("profile", profile_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("history", history_cmd))
    app.add_handler(CommandHandler("ping", ping_cmd))
    app.add_handler(CommandHandler("setup", setup_cmd))
    app.add_handler(CommandHandler("rules", rules_cmd))
    app.add_handler(CommandHandler("antilink", antilink_cmd))
    app.add_handler(CommandHandler("antispam", antispam_cmd))
    app.add_handler(CommandHandler("welcome", welcome_cmd))
    app.add_handler(CommandHandler("groupinfo", groupinfo_cmd))
    app.add_handler(CommandHandler("warn", warn_cmd))
    app.add_handler(CommandHandler("mute", mute_cmd))
    app.add_handler(CommandHandler("unmute", unmute_cmd))
    app.add_handler(CommandHandler("kick", kick_cmd))
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))
    app.add_handler(CommandHandler("convert", convert_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CallbackQueryHandler(callback, pattern=r"^(?!file\|)"))
    app.add_handler(CallbackQueryHandler(file_callback, pattern=r"^file\|"))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.VIDEO | filters.AUDIO, media_file_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    log.info("%s starting", BOT_NAME)
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
