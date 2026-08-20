--- bot.py (原始)
import os
import logging
import asyncio
import re
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode
from PIL import Image
import io
import aiohttp
from dotenv import load_dotenv

# بارگذاری متغیرهای محیطی
load_dotenv()

# تنظیمات لاگینگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# متغیرهای محیطی از Railway
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
SOURCE_CHANNEL_ID = os.getenv('SOURCE_CHANNEL_ID')  # آیدی کانال مبدا (مثلا -1001234567890)
DEST_CHANNEL_ID = os.getenv('DEST_CHANNEL_ID')      # آیدی کانال مقصد
ADMIN_USER_IDS = os.getenv('ADMIN_USER_IDS', '').split(',')  # آیدی ادمین‌هایی که می‌توانند تنظیمات را تغییر دهند

# تامنیل پیش‌فرض (اختیاری)
DEFAULT_THUMBNAIL_URL = os.getenv('DEFAULT_THUMBNAIL_URL', None)

# صف برای پردازش پیام‌ها
message_queue = asyncio.Queue()
is_processing = False

# دیکشنری برای ذخیره کلمات جایگزین
replacement_words = {}

# کلاینت‌ها
app = None  # User Client
bot = None  # Bot Client

async def download_thumbnail(url: str) -> bytes:
    """دانلود تامنیل از URL"""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.read()

async def create_custom_thumbnail(image_data: bytes, text: str = None) -> bytes:
    """ساخت تامنیل سفارشی با PIL"""
    try:
        img = Image.open(io.BytesIO(image_data))
        img = img.convert('RGB')
        img = img.resize((1280, 720))  # سایز استاندارد

        output = io.BytesIO()
        img.save(output, format='JPEG', quality=85)
        return output.getvalue()
    except Exception as e:
        logger.error(f"Error creating thumbnail: {e}")
        return image_data

def replace_text_in_message(text: str) -> str:
    """جایگزینی کلمات در متن پیام"""
    if not text:
        return text

    result = text
    for old_word, new_word in replacement_words.items():
        result = result.replace(old_word, new_word)

    return result

def strip_premium_emojis(text: str) -> str:
    """حذف ایموجی‌های پرمیوم و تبدیل به نسخه عادی"""
    if not text:
        return text

    # حذف کاراکترهای خاص ایموجی‌های پرمیوم تلگرام
    # ایموجی‌های پرمیوم معمولاً در محدوده‌های خاصی از یونیکد قرار دارند
    premium_ranges = [
        (0x1F4A9, 0x1F4A9),  # مثال: برخی ایموجی‌های خاص
        # می‌توانید محدوده‌های بیشتری اضافه کنید
    ]

    result = []
    for char in text:
        code_point = ord(char)
        is_premium = False
        for start, end in premium_ranges:
            if start <= code_point <= end:
                is_premium = True
                break
        if not is_premium:
            result.append(char)

    return ''.join(result)

async def process_message(message):
    """پردازش یک پیام از کانال مبدا و کپی به کانال مقصد"""
    global is_processing
    try:
        # دریافت محتوای پیام
        caption = message.caption if message.caption else ""

        # جایگزینی کلمات
        caption = replace_text_in_message(caption)

        # حذف ایموجی‌های پرمیوم
        caption = strip_premium_emojis(caption)

        # بررسی نوع محتوا و کپی به کانال مقصد
        if message.photo:
            # دریافت عکس
            photo = message.photo[-1]  # بهترین کیفیت

            # دانلود عکس
            photo_path = await app.download_media(photo.file_id)

            # اگر تامنیل سفارشی داریم
            thumb_path = None
            if DEFAULT_THUMBNAIL_URL:
                thumb_data = await download_thumbnail(DEFAULT_THUMBNAIL_URL)
                thumb_io = io.BytesIO(thumb_data)
                thumb_io.name = "thumbnail.jpg"
                thumb_path = thumb_io

            # ارسال به کانال مقصد بدون فوروارد
            await bot.send_photo(
                chat_id=DEST_CHANNEL_ID,
                photo=photo_path,
                caption=caption,
                parse_mode=ParseMode.HTML,
                thumb=thumb_path
            )

            # پاک کردن فایل موقت
            if os.path.exists(photo_path):
                os.remove(photo_path)

        elif message.video:
            # دریافت ویدیو
            video_path = await app.download_media(message.video.file_id)

            # دانلود تامنیل اگر وجود دارد
            thumb_path = None
            if message.video.thumbs:
                thumb_data = await app.download_media(message.video.thumbs[0].file_id)

                # اگر تامنیل سفارشی داریم
                if DEFAULT_THUMBNAIL_URL:
                    custom_thumb = await download_thumbnail(DEFAULT_THUMBNAIL_URL)
                    thumb_io = io.BytesIO(custom_thumb)
                    thumb_io.name = "thumbnail.jpg"
                    thumb_path = thumb_io
                else:
                    thumb_path = thumb_data

            # ارسال ویدیو با تامنیل سفارشی
            await bot.send_video(
                chat_id=DEST_CHANNEL_ID,
                video=video_path,
                caption=caption,
                parse_mode=ParseMode.HTML,
                thumb=thumb_path
            )

            # پاک کردن فایل موقت
            if os.path.exists(video_path):
                os.remove(video_path)

        elif message.document:
            # دریافت فایل
            file_path = await app.download_media(message.document.file_id)

            # ارسال فایل
            await bot.send_document(
                chat_id=DEST_CHANNEL_ID,
                document=file_path,
                caption=caption,
                parse_mode=ParseMode.HTML
            )

            # پاک کردن فایل موقت
            if os.path.exists(file_path):
                os.remove(file_path)

        elif message.audio:
            # دریافت صوت
            audio_path = await app.download_media(message.audio.file_id)

            # دانلود تامنیل اگر وجود دارد
            thumb_path = None
            if message.audio.thumbs:
                thumb_path = await app.download_media(message.audio.thumbs[0].file_id)

            # ارسال صوت
            await bot.send_audio(
                chat_id=DEST_CHANNEL_ID,
                audio=audio_path,
                caption=caption,
                parse_mode=ParseMode.HTML,
                thumb=thumb_path,
                performer=message.audio.performer,
                title=message.audio.title
            )

            # پاک کردن فایل موقت
            if os.path.exists(audio_path):
                os.remove(audio_path)

        elif message.voice:
            # دریافت ویس
            voice_path = await app.download_media(message.voice.file_id)

            # ارسال ویس
            await bot.send_voice(
                chat_id=DEST_CHANNEL_ID,
                voice=voice_path,
                caption=caption,
                parse_mode=ParseMode.HTML
            )

            # پاک کردن فایل موقت
            if os.path.exists(voice_path):
                os.remove(voice_path)

        elif message.text:
            # ارسال متن ساده
            await bot.send_message(
                chat_id=DEST_CHANNEL_ID,
                text=caption,
                parse_mode=ParseMode.HTML
            )

        else:
            logger.info(f"Unsupported message type: {message}")

        logger.info(f"Message processed successfully from {message.chat.id}")

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
    finally:
        is_processing = False

async def queue_worker():
    """کارگر پردازش صف"""
    global is_processing

    while True:
        if not message_queue.empty():
            is_processing = True
            message = await message_queue.get()
            await process_message(message)
            message_queue.task_done()
        else:
            await asyncio.sleep(1)

@bot.on_message(filters.command("start"))
async def start_command(client, message):
    """دستور /start"""
    await message.reply_text(
        "سلام! من ربات کپی محتوا هستم.\n"
        "برای تنظیم کلمات جایگزین از دستور /replace استفاده کنید.\n"
        "مثال: /replace قدیمی جدید"
    )

@bot.on_message(filters.command("replace"))
async def replace_command(client, message):
    """دستور /replace برای تنظیم کلمات جایگزین"""
    user_id = str(message.from_user.id)

    if user_id not in ADMIN_USER_IDS:
        await message.reply_text("شما اجازه استفاده از این دستور را ندارید.")
        return

    args = message.text.split()[1:]
    if len(args) < 2:
        await message.reply_text(
            "لطفا کلمه قدیمی و جدید را وارد کنید.\n"
            "مثال: /replace قدیمی جدید"
        )
        return

    old_word = args[0]
    new_word = ' '.join(args[1:])

    replacement_words[old_word] = new_word

    await message.reply_text(
        f"کلمه '{old_word}' با '{new_word}' جایگزین خواهد شد.\n"
        f"تعداد کل کلمات جایگزین: {len(replacement_words)}"
    )

@bot.on_message(filters.command("replacements"))
async def show_replacements_command(client, message):
    """نمایش کلمات جایگزین"""
    user_id = str(message.from_user.id)

    if user_id not in ADMIN_USER_IDS:
        await message.reply_text("شما اجازه استفاده از این دستور را ندارید.")
        return

    if not replacement_words:
        await message.reply_text("هیچ کلمه جایگزینی تنظیم نشده است.")
        return

    text = "کلمات جایگزین:\n"
    for old, new in replacement_words.items():
        text += f"{old} → {new}\n"

    await message.reply_text(text)

@bot.on_message(filters.command("clear"))
async def clear_replacements_command(client, message):
    """پاک کردن همه کلمات جایگزین"""
    user_id = str(message.from_user.id)

    if user_id not in ADMIN_USER_IDS:
        await message.reply_text("شما اجازه استفاده از این دستور را ندارید.")
        return

    replacement_words.clear()
    await message.reply_text("همه کلمات جایگزین پاک شدند.")

@bot.on_message(filters.command("status"))
async def status_command(client, message):
    """نمایش وضعیت ربات"""
    user_id = str(message.from_user.id)

    if user_id not in ADMIN_USER_IDS:
        await message.reply_text("شما اجازه استفاده از این دستور را ندارید.")
        return

    status = f"""
وضعیت ربات:
- تعداد پیام‌ها در صف: {message_queue.qsize()}
- در حال پردازش: {is_processing}
- تعداد کلمات جایگزین: {len(replacement_words)}
- کانال مبدا: {SOURCE_CHANNEL_ID}
- کانال مقصد: {DEST_CHANNEL_ID}
"""

    await message.reply_text(status)

async def monitor_channel():
    """مانیتورینگ کانال مبدا با استفاده از User Client"""
    logger.info(f"Starting to monitor channel: {SOURCE_CHANNEL_ID}")

    last_message_id = 0

    while True:
        try:
            # دریافت آخرین پیام‌های کانال
            async for message in app.get_chat_history(SOURCE_CHANNEL_ID, limit=1):
                if message and message.id > last_message_id:
                    logger.info(f"New message detected: {message.id}")

                    # اضافه کردن به صف
                    await message_queue.put(message)
                    last_message_id = message.id

            await asyncio.sleep(2)  # بررسی هر 2 ثانیه

        except Exception as e:
            logger.error(f"Error monitoring channel: {e}", exc_info=True)
            await asyncio.sleep(5)

async def main():
    """تابع اصلی"""
    global app, bot

    # بررسی متغیرهای محیطی
    if not API_ID or not API_HASH:
        logger.error("API_ID or API_HASH not found in environment variables")
        return

    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not found in environment variables")
        return

    if not SOURCE_CHANNEL_ID or not DEST_CHANNEL_ID:
        logger.error("SOURCE_CHANNEL_ID or DEST_CHANNEL_ID not found")
        return

    logger.info(f"Source Channel: {SOURCE_CHANNEL_ID}")
    logger.info(f"Dest Channel: {DEST_CHANNEL_ID}")

    # ساخت کلاینت کاربر (User Client)
    app = Client(
        name="user_session",
        api_id=int(API_ID),
        api_hash=API_HASH,
        session_string=os.getenv('SESSION_STRING', None)
    )

    # ساخت کلاینت ربات (Bot Client)
    bot = Client(
        name="bot_session",
        api_token=BOT_TOKEN
    )

    # شروع کلاینت‌ها
    await app.start()
    await bot.start()

    logger.info("User client and Bot client started successfully")

    # شروع کارگر صف
    asyncio.create_task(queue_worker())

    # شروع مانیتورینگ کانال
    asyncio.create_task(monitor_channel())

    # نگه داشتن برنامه در حال اجرا
    while True:
        await asyncio.sleep(1)

if __name__ == '__main__':
    asyncio.run(main())


+++ bot.py (修改后)
import os
import asyncio
import logging
import sqlite3
import re
from typing import Optional, Dict
from pyrogram import Client, filters, enums
from pyrogram.types import Message
from pyrogram.handlers import MessageHandler
from pyrogram.errors import FloodWait, PeerIdInvalid, ChannelPrivate, UserNotParticipant
from dotenv import load_dotenv
import aiohttp
from PIL import Image
import io

# تنظیمات لاگینگ
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

# خواندن متغیرهای محیطی
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
SOURCE_CHANNEL_ID = os.getenv("SOURCE_CHANNEL_ID")
DEST_CHANNEL_ID = os.getenv("DEST_CHANNEL_ID")
ADMIN_USER_IDS = os.getenv("ADMIN_USER_IDS", "").split(",")
DEFAULT_THUMBNAIL_URL = os.getenv("DEFAULT_THUMBNAIL_URL")
SESSION_STRING = os.getenv("SESSION_STRING")

# اعتبارسنجی متغیرهای ضروری
if not all([API_ID, API_HASH, BOT_TOKEN, SOURCE_CHANNEL_ID, DEST_CHANNEL_ID]):
    logger.error("❌ متغیرهای محیطی ضروری تنظیم نشده‌اند!")
    exit(1)

# تبدیل آیدی ادمین‌ها به عدد
admin_ids = []
for admin_id in ADMIN_USER_IDS:
    try:
        admin_ids.append(int(admin_id.strip()))
    except ValueError:
        pass

# اتصال به دیتابیس
def init_db():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS replacements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_word TEXT UNIQUE,
            target_word TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER,
            status TEXT DEFAULT 'pending'
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ایجاد کلاینت‌ها
bot_client = None
user_client = None

if SESSION_STRING:
    user_client = Client(
        "user_session",
        api_id=int(API_ID),
        api_hash=API_HASH,
        session_string=SESSION_STRING
    )
    logger.info("✅ یوزر کلاینت با SESSION_STRING راه‌اندازی شد.")
else:
    logger.warning("⚠️ SESSION_STRING یافت نشد. ربات فقط با توکن ربات اجرا می‌شود.")
    logger.warning("⚠️ برای خواندن کانال‌های خصوصی بدون ادمین، حتماً SESSION_STRING لازم است.")

bot_client = Client(
    "bot_session",
    api_id=int(API_ID),
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# صف پیام‌ها
message_queue = asyncio.Queue()
is_processing = False

# توابع کمکی
def get_replacements() -> Dict[str, str]:
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT source_word, target_word FROM replacements')
    replacements = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return replacements

def add_replacement(source: str, target: str):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT OR REPLACE INTO replacements (source_word, target_word) VALUES (?, ?)', (source, target))
        conn.commit()
    finally:
        conn.close()

def remove_replacement(source: str):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    try:
        cursor.execute('DELETE FROM replacements WHERE source_word = ?', (source,))
        conn.commit()
    finally:
        conn.close()

def remove_premium_emojis(text: str) -> str:
    if not text:
        return ""
    # حذف ایموجی‌ها (برای جلوگیری از نمایش پرمیوم)
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F"  # emoticons
        u"\U0001F300-\U0001F5FF"  # symbols & pictographs
        u"\U0001F680-\U0001F6FF"  # transport & map symbols
        u"\U0001F700-\U0001F77F"  # alchemical symbols
        u"\U0001F780-\U0001F7FF"  # Geometric Shapes Extended
        u"\U0001F800-\U0001F8FF"  # Supplemental Arrows-C
        u"\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
        u"\U0001FA00-\U0001FA6F"  # Chess Symbols
        u"\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
        u"\U00002702-\U000027B0"  # Dingbats
        u"\U000024C2-\U0001F251"
        "]+", flags=re.UNICODE)
    return emoji_pattern.sub(r'', text)

async def download_thumbnail(url: str) -> Optional[str]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    image_data = await response.read()
                    img = Image.open(io.BytesIO(image_data))
                    img_path = "temp_thumb.jpg"
                    img.save(img_path, "JPEG")
                    return img_path
    except Exception as e:
        logger.error(f"خطا در دانلود تامنیل: {e}")
    return None

async def process_message(msg: Message):
    global is_processing
    try:
        replacements = get_replacements()
        caption = msg.caption or ""

        # جایگزینی کلمات در کپشن
        for source, target in replacements.items():
            caption = caption.replace(source, target)

        # حذف ایموجی‌های پرمیوم
        caption = remove_premium_emojis(caption)

        # تعیین تامنیل جدید
        thumb_path = None
        if DEFAULT_THUMBNAIL_URL:
            thumb_path = await download_thumbnail(DEFAULT_THUMBNAIL_URL)

        # کپی پیام به کانال مقصد
        if msg.photo:
            file_id = msg.photo.file_id
            await bot_client.send_photo(
                chat_id=DEST_CHANNEL_ID,
                photo=file_id,
                caption=caption,
                parse_mode=enums.ParseMode.MARKDOWN,
                thumb=thumb_path
            )
        elif msg.video:
            file_id = msg.video.file_id
            await bot_client.send_video(
                chat_id=DEST_CHANNEL_ID,
                video=file_id,
                caption=caption,
                parse_mode=enums.ParseMode.MARKDOWN,
                thumb=thumb_path
            )
        elif msg.document:
            file_id = msg.document.file_id
            await bot_client.send_document(
                chat_id=DEST_CHANNEL_ID,
                document=file_id,
                caption=caption,
                parse_mode=enums.ParseMode.MARKDOWN,
                thumb=thumb_path
            )
        elif msg.audio:
            file_id = msg.audio.file_id
            await bot_client.send_audio(
                chat_id=DEST_CHANNEL_ID,
                audio=file_id,
                caption=caption,
                parse_mode=enums.ParseMode.MARKDOWN,
                thumb=thumb_path
            )
        elif msg.voice:
            file_id = msg.voice.file_id
            await bot_client.send_voice(
                chat_id=DEST_CHANNEL_ID,
                voice=file_id,
                caption=caption,
                parse_mode=enums.ParseMode.MARKDOWN
            )
        elif msg.text:
            await bot_client.send_message(
                chat_id=DEST_CHANNEL_ID,
                text=caption,
                parse_mode=enums.ParseMode.MARKDOWN
            )
        else:
            # کپی عمومی برای سایر انواع پیام
            await msg.copy(
                chat_id=DEST_CHANNEL_ID,
                caption=caption,
                parse_mode=enums.ParseMode.MARKDOWN
            )

        logger.info(f"پیام {msg.id} با موفقیت کپی شد.")

    except Exception as e:
        logger.error(f"خطا در پردازش پیام {msg.id}: {e}")
    finally:
        is_processing = False
        if thumb_path and os.path.exists(thumb_path):
            os.remove(thumb_path)

async def queue_worker():
    global is_processing
    while True:
        if not message_queue.empty() and not is_processing:
            is_processing = True
            msg = await message_queue.get()
            await process_message(msg)
            message_queue.task_done()
        await asyncio.sleep(1)

# هندلرهای ربات
async def start_handler(client: Client, message: Message):
    if message.from_user.id not in admin_ids:
        return
    await message.reply_text(
        "👋 سلام! ربات آماده است.\n"
        "دستورات موجود:\n"
        "/replace <کلمه مبدا> <کلمه مقصد> - افزودن جایگزینی\n"
        "/remove <کلمه> - حذف جایگزینی\n"
        "/list - لیست جایگزینی‌ها\n"
        "/status - وضعیت صف"
    )

async def replace_handler(client: Client, message: Message):
    if message.from_user.id not in admin_ids:
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.reply_text("❌ فرمت صحیح: /replace <کلمه مبدا> <کلمه مقصد>")
        return
    source = args[1]
    target = args[2]
    add_replacement(source, target)
    await message.reply_text(f"✅ جایگزینی '{source}' به '{target}' افزوده شد.")

async def remove_handler(client: Client, message: Message):
    if message.from_user.id not in admin_ids:
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text("❌ فرمت صحیح: /remove <کلمه>")
        return
    source = args[1]
    remove_replacement(source)
    await message.reply_text(f"✅ جایگزینی '{source}' حذف شد.")

async def list_handler(client: Client, message: Message):
    if message.from_user.id not in admin_ids:
        return
    replacements = get_replacements()
    if not replacements:
        await message.reply_text("📭 هیچ جایگزینی ثبت نشده است.")
        return
    text = "📋 لیست جایگزینی‌ها:\n"
    for src, tgt in replacements.items():
        text += f"- {src} ➜ {tgt}\n"
    await message.reply_text(text)

async def status_handler(client: Client, message: Message):
    if message.from_user.id not in admin_ids:
        return
    queue_size = message_queue.qsize()
    await message.reply_text(f"📊 وضعیت صف: {queue_size} پیام در انتظار")

async def forward_handler(client: Client, message: Message):
    # بررسی اینکه آیا پیام از کانال مبدا است
    if str(message.chat.id) == SOURCE_CHANNEL_ID:
        await message_queue.put(message)
        logger.info(f"پیام {message.id} از کانال مبدا به صف اضافه شد.")

async def main():
    # شروع ربات بات
    await bot_client.start()
    logger.info("🤖 ربات بات شروع شد.")

    # ثبت هندلرها برای ربات بات
    bot_client.add_handler(MessageHandler(start_handler, filters.command("start")))
    bot_client.add_handler(MessageHandler(replace_handler, filters.command("replace")))
    bot_client.add_handler(MessageHandler(remove_handler, filters.command("remove")))
    bot_client.add_handler(MessageHandler(list_handler, filters.command("list")))
    bot_client.add_handler(MessageHandler(status_handler, filters.command("status")))
    bot_client.add_handler(MessageHandler(forward_handler, filters.chat(int(SOURCE_CHANNEL_ID))))

    # شروع یوزر بات اگر SESSION_STRING وجود دارد
    if user_client:
        await user_client.start()
        logger.info("👤 یوزر بات شروع شد.")
        # ثبت هندلر برای یوزر بات (برای دریافت پیام از کانال مبدا)
        user_client.add_handler(MessageHandler(forward_handler, filters.chat(int(SOURCE_CHANNEL_ID))))

    # شروع ورکر صف
    asyncio.create_task(queue_worker())

    logger.info("✅ ربات آماده به کار است. تا زمانی که متوقف نشده، اجرا می‌شود...")
    # نگه داشتن برنامه در حال اجرا
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 ربات متوقف شد.")
    except Exception as e:
        logger.critical(f"💥 خطای بحرانی: {e}", exc_info=True)
