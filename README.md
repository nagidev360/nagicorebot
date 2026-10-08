# NagiCoreBot

Production-oriented Telegram bot for DM + Group use.

## Features
- DM menu and user profile
- YouTube / Instagram URL detection
- MP4 video and MP3 audio downloads for content the user is authorized to download
- Uploaded media conversion to MP3 / MP4
- Group setup, welcome messages, rules
- Anti-link and anti-spam controls
- Warn, mute, kick and ban
- SQLite user/group persistence
- Admin broadcast and statistics
- Rate limiting and temporary-file cleanup

## Setup
1. Install Python 3.11+ and FFmpeg.
2. Copy .env.example to .env.
3. Put your BotFather token in BOT_TOKEN.
4. Put owner Telegram IDs in ADMIN_IDS (comma separated).
5. Install dependencies with pip install -r requirements.txt.
6. Start with python bot.py.

Never commit .env or your bot token.

## Commands
DM: /start /menu /help /profile /id /stats /convert
Group: /setup /rules /welcome /antispam /antilink /warn /mute /unmute /kick /ban /unban /groupinfo /id /ping
Admin: /admin /broadcast /stats

Media URLs can also be pasted directly. The bot does not bypass private, DRM-protected, login-protected, or other access restrictions.
