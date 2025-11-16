import os
import re
import asyncio
import logging
import time
from collections import deque
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events, types
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ======================
#  LOGGING SETUP
# ======================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)

app = Flask(__name__)

# ======================
#  ENV READER
# ======================
def get_env(name, is_int=True, optional=False):
    try:
        value = os.environ[name]
        return int(value) if is_int else value
    except:
        if optional:
            return None
        logging.critical(f"Missing required environment variable: {name}")
        raise

# ======================
#  LOAD CONFIG
# ======================
api_id = get_env("API_ID")
api_hash = get_env("API_HASH", is_int=False)
bot_token = get_env("BOT_TOKEN", is_int=False)

source_channels = [int(x) for x in get_env("SOURCE_CHANNELS", is_int=False).split(",")]
target_channels = [int(x) for x in get_env("TARGET_CHANNELS", is_int=False).split(",")]

queue_delay = int(get_env("QUEUE_DELAY", optional=True) or 120)
rate_limit = int(get_env("RATE_LIMIT", optional=True) or 60)
port = int(get_env("PORT", optional=True) or 8080)

# ======================
#  KEEP ALIVE (Replit)
# ======================
@app.route('/')
def home():
    return "Bot is running!"

def run_web():
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    Thread(target=run_web, daemon=True).start()

# ======================
#  TELEGRAM CLIENT
# ======================
client = TelegramClient('bot_session', api_id, api_hash)

message_queue = deque()
is_forwarding = False
last_forward_time = 0

# ======================
#  MESSAGE PARSER
# ======================
def parse_and_format_message(text):
    """
    Extracts Code, Amount, Token, Progress
    Removes hyperlinks
    Rebuilds message in required format
    """

    # Remove all HTML/Telegram links
    text = re.sub(r'<[^>]+>', '', text)

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) < 3:
        return None

    # ----- Line 1 -----
    # 💰 ± 0.00000002 BNB
    match_amount = re.search(r'±\s*([\d.]+)\s*([A-Za-z0-9]+)', lines[0])
    if not match_amount:
        return None

    amount = match_amount.group(1)
    token = match_amount.group(2)

    # ----- Line 2 -----
    # 🧧 Claimed: 646 / 711
    match_claim = re.search(r'Claimed:\s*(\d+)\s*/\s*(\d+)', lines[1])
    if not match_claim:
        return None

    claimed = match_claim.group(1)
    total = match_claim.group(2)

    # ----- Line 3 -----
    # 🎁 IJAU5UL6
    match_code = re.search(r'🎁\s*([A-Z0-9]+)', lines[2])
    if not match_code:
        return None

    code = match_code.group(1)

    # ----- Build Output -----
    formatted = (
        f"🎁 Code: {code}\n"
        f"💰 Amount: {amount} {token}\n"
        f"🧧 Progress: {claimed} / {total}\n\n"
        f"#Binance #RedPacketHub"
    )
    return formatted


# ======================
#  NEW MESSAGE HANDLER
# ======================
@client.on(events.NewMessage(chats=source_channels))
async def handler(event):
    global is_forwarding, last_forward_time

    try:
        raw = event.message.message or ""

        # skip if contains a link anywhere
        if "http://" in raw or "https://" in raw or "<a href=" in raw:
            logging.info("Skipped because contains hyperlink")
            return

        parsed = parse_and_format_message(raw)
        if not parsed:
            logging.info("Skipped: format does not match.")
            return

        current = time.time()

        # Send immediately or queue
        if not is_forwarding or (current - last_forward_time > rate_limit):
            await forward_to_targets(parsed)
            last_forward_time = current
            is_forwarding = True
            client.loop.create_task(process_queue())
        else:
            message_queue.append(parsed)
            logging.info(f"Queued message. Queue size: {len(message_queue)}")

    except Exception as e:
        logging.error(f"Error in handler: {str(e)}")


# ======================
#  FORWARDING
# ======================
async def forward_to_targets(text):
    """Send formatted message to all target channels."""
    for channel in target_channels:
        try:
            await client.send_message(channel, text, link_preview=False)
            logging.info(f"Forwarded to {channel}")
            await asyncio.sleep(1)
        except Exception as e:
            logging.error(f"Send error for {channel}: {str(e)}")
            await asyncio.sleep(2)


async def process_queue():
    global is_forwarding

    while message_queue:
        await asyncio.sleep(queue_delay)
        msg = message_queue.popleft()
        await forward_to_targets(msg)

    is_forwarding = False


# ======================
#  RUN BOT
# ======================
async def run_bot():
    await client.start(bot_token=bot_token)
    logging.info("Bot started successfully!")
    await client.run_until_disconnected()

if __name__ == "__main__":
    keep_alive()
    asyncio.run(run_bot())
