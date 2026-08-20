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
import logging
import asyncio
import re
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.handlers import MessageHandler
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

# کلاینت‌ها - بعداً مقداردهی می‌شوند
app = None  # User Client
bot = None  # Bot Client

# لیست توابع دکوراتور برای ثبت بعد از شروع بات
handler_decorators = []

def register_handler(func):
    """ذخیره تابع دکوراتور برای ثبت بعد از شروع بات"""
    handler_decorators.append(func)
    return func

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

# تعریف هندلرها - بعد از شروع بات ثبت می‌شوند
async def start_command(client, message):
    """دستور /start"""
    await message.reply_text(
        "سلام! من ربات کپی محتوا هستم.\n"
        "برای تنظیم کلمات جایگزین از دستور /replace استفاده کنید.\n"
        "مثال: /replace قدیمی جدید"
    )

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

async def clear_replacements_command(client, message):
    """پاک کردن همه کلمات جایگزین"""
    user_id = str(message.from_user.id)

    if user_id not in ADMIN_USER_IDS:
        await message.reply_text("شما اجازه استفاده از این دستور را ندارید.")
        return

    replacement_words.clear()
    await message.reply_text("همه کلمات جایگزین پاک شدند.")

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

    # ثبت هندلرها بعد از شروع بات
    bot.add_handler(MessageHandler(start_command, filters.command("start")))
    bot.add_handler(MessageHandler(replace_command, filters.command("replace")))
    bot.add_handler(MessageHandler(show_replacements_command, filters.command("replacements")))
    bot.add_handler(MessageHandler(clear_replacements_command, filters.command("clear")))
    bot.add_handler(MessageHandler(status_command, filters.command("status")))

    logger.info("All command handlers registered")

    # شروع کارگر صف
    asyncio.create_task(queue_worker())

    # شروع مانیتورینگ کانال
    asyncio.create_task(monitor_channel())

    # نگه داشتن برنامه در حال اجرا
    while True:
        await asyncio.sleep(1)

if __name__ == '__main__':
    asyncio.run(main())
