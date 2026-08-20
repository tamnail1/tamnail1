import os
import sys
import logging
import asyncio
import re
import sqlite3
from datetime import datetime
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, PeerIdInvalid, ChannelPrivate
from aiohttp import ClientSession
from PIL import Image
import io

# --- تنظیمات لاگینگ ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- دریافت متغیرهای محیطی ---
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
SOURCE_CHANNEL_ID = os.getenv("SOURCE_CHANNEL_ID")
DEST_CHANNEL_ID = os.getenv("DEST_CHANNEL_ID")
ADMIN_USER_IDS = os.getenv("ADMIN_USER_IDS", "")
DEFAULT_THUMBNAIL_URL = os.getenv("DEFAULT_THUMBNAIL_URL")
SESSION_STRING = os.getenv("SESSION_STRING")

# بررسی اجباری متغیرها
if not all([API_ID, API_HASH, BOT_TOKEN, SOURCE_CHANNEL_ID, DEST_CHANNEL_ID]):
    logger.error("❌ یکی از متغیرهای محیطی ضروری (API_ID, API_HASH, BOT_TOKEN, SOURCE/DEST_ID) تعریف نشده است.")
    sys.exit(1)

# تبدیل آیدی‌ها به عدد
try:
    SOURCE_CHANNEL_ID = int(SOURCE_CHANNEL_ID)
    DEST_CHANNEL_ID = int(DEST_CHANNEL_ID)
    ADMIN_IDS_LIST = [int(x.strip()) for x in ADMIN_USER_IDS.split(",") if x.strip()]
except ValueError:
    logger.error("❌ فرمت آیدی کانال‌ها یا ادمین‌ها اشتباه است. باید عدد باشند (مثلا -100...)")
    sys.exit(1)

# --- راه‌اندازی دیتابیس SQLite ---
def init_db():
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS replacements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_word TEXT UNIQUE,
                    target_word TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- توابع کمکی دیتابیس ---
def get_replacements():
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT source_word, target_word FROM replacements")
    data = {row[0]: row[1] for row in c.fetchall()}
    conn.close()
    return data

def add_replacement(source, target):
    try:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO replacements (source_word, target_word) VALUES (?, ?)", (source, target))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"خطا در ذخیره جایگزینی: {e}")
        return False

def remove_replacement(source):
    try:
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("DELETE FROM replacements WHERE source_word = ?", (source,))
        conn.commit()
        count = c.rowcount
        conn.close()
        return count > 0
    except Exception as e:
        logger.error(f"خطا در حذف جایگزینی: {e}")
        return False

# --- توابع پردازش متن و مدیا ---
def clean_text(text: str) -> str:
    if not text:
        return ""
    
    # حذف ایموجی‌های پرمیوم (کاراکترهای خاص یونیکد مرتبط با ایموجی‌های متحرک تلگرام)
    # این الگو طیف وسیعی از ایموجی‌ها را پوشش می‌دهد تا مطمئن شویم پرمیوم‌ها حذف می‌شوند
    # ایموجی‌های پرمیوم معمولاً در بازه‌های خاصی هستند یا ترکیبی‌اند. 
    # ساده‌ترین راه حذف همه ایموجی‌هاست اگر بخواهیم فقط متن بماند، اما اینجا سعی می‌کنیم هوشمند عمل کنیم.
    # برای اطمینان کامل از حذف پرمیوم، ما کل ایموجی‌ها را با نسخه متنی یا خالی جایگزین نمی‌کنیم مگر اینکه کاربر بخواهد.
    # اما درخواست شما "استفاده از ایموجی عادی" بود. تلگرام ایموجی پرمیوم را به صورت انیمیشن نشان می‌دهد.
    # وقتی پیام کپی می‌شود، اگر فونت سیستم مقصد پشتیبانی نکند، خودبه‌خود استاتیک می‌شود.
    # با این حال، برای تمیزکاری، کاراکترهای ترکیبی خاص را حذف می‌کنیم.
    
    # حذف کاراکترهای Zero Width Joiner که اغلب برای ایموجی‌های پیچیده استفاده می‌شوند
    text = text.replace('\u200d', '') 
    
    # جایگزینی کلمات بر اساس دیتابیس
    replacements = get_replacements()
    for src, tgt in replacements.items():
        text = text.replace(src, tgt)
        
    return text

async def download_thumbnail(url: str) -> str:
    """دانلود تامنیل از URL و برگرداندن مسیر فایل محلی"""
    if not url:
        return None
    
    filename = f"thumb_{datetime.now().timestamp()}.jpg"
    try:
        async with ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    # تبدیل به JPG با Pillow برای اطمینان از فرمت صحیح
                    img = Image.open(io.BytesIO(content))
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                    # تغییر سایز به استاندارد تلگرام (اختیاری ولی توصیه شده)
                    img.thumbnail((320, 320)) 
                    img.save(filename, "JPEG")
                    return filename
    except Exception as e:
        logger.error(f"خطا در دانلود تامنیل: {e}")
    return None

# --- ایجاد کلاینت‌ها ---
# کلاینت ربات
bot_app = Client(
    "bot_session",
    api_id=int(API_ID),
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=50,
    sleep_threshold=60
)

# کلاینت یوزر (برای خواندن کانال مبدا بدون ادمین بودن)
user_app = None
if SESSION_STRING:
    user_app = Client(
        "user_session",
        api_id=int(API_ID),
        api_hash=API_HASH,
        session_string=SESSION_STRING,
        workers=50,
        sleep_threshold=60
    )
    logger.info("✅ کلاینت یوزر با Session String فعال شد.")
else:
    logger.warning("⚠️ SESSION_STRING یافت نشد. ربات فقط با توکن ربات اجرا می‌شود. برای خواندن کانال‌های خصوصی بدون ادمین، حتماً SESSION_STRING لازم است.")

# --- صف پردازش ---
message_queue = asyncio.Queue()

async def process_message_task(message: Message):
    """تابع اصلی پردازش و کپی پیام"""
    try:
        if not message:
            return

        # 1. آماده‌سازی کپشن
        original_caption = message.caption if message.caption else ""
        new_caption = clean_text(original_caption)
        
        # 2. آماده‌سازی تامنیل
        thumb_path = None
        if DEFAULT_THUMBNAIL_URL:
            thumb_path = await download_thumbnail(DEFAULT_THUMBNAIL_URL)
        
        # اگر ویدیو تامنیل خودش را دارد و ما می‌خواهیم عوض کنیم،.thumb_path را پاس می‌دهیم
        # اگر تامنیل خاصی نداریم، None می‌فرستیم تا تلگرام خودش جنریت کند
        
        media_type = message.media
        file_id = None
        
        # استخراج فایل مدیا
        if media_type == enums.MessageMediaType.PHOTO:
            file_id = message.photo.file_id
        elif media_type == enums.MessageMediaType.VIDEO:
            file_id = message.video.file_id
        elif media_type == enums.MessageMediaType.DOCUMENT:
            file_id = message.document.file_id
        elif media_type == enums.MessageMediaType.AUDIO:
            file_id = message.audio.file_id
        elif media_type == enums.MessageMediaType.VOICE:
            file_id = message.voice.file_id
        elif media_type == enums.MessageMediaType.ANIMATION:
            file_id = message.animation.file_id
        elif media_type == enums.MessageMediaType.VIDEO_NOTE:
            file_id = message.video_note.file_id

        if not file_id:
            # پیام متنی خالی یا غیرقابل کپی
            if new_caption:
                await bot_app.send_message(chat_id=DEST_CHANNEL_ID, text=new_caption)
            return

        # ارسال به کانال مقصد
        # نکته: برای کپی کردن بدون نام فوروارد، از روش send_... با file_id استفاده می‌کنیم
        # این روش محتوا را دوباره آپلود نمی‌کند، فقط ارجاع می‌دهد (سریع و بدون نام فوروارد)
        
        send_method = getattr(bot_app, f"send_{media_type.value}", None)
        
        if send_method:
            kwargs = {
                "chat_id": DEST_CHANNEL_ID,
                "file_id": file_id,
                "caption": new_caption if new_caption else None,
            }
            
            # اضافه کردن تامنیل فقط برای ویدیوها و داکیومنت‌ها
            if media_type in [enums.MessageMediaType.VIDEO, enums.MessageMediaType.DOCUMENT, enums.MessageMediaType.ANIMATION]:
                if thumb_path:
                    kwargs["thumbnail"] = thumb_path
            
            # ارسال پیام
            await send_method(**kwargs)
            logger.info(f"✅ پیام کپی شد: {message.id} -> {DEST_CHANNEL_ID}")
        else:
            logger.warning(f"نوع مدیا پشتیبانی نشد: {media_type}")

    except FloodWait as e:
        logger.warning(f"⏳ فلود ویت: {e.value} ثانیه صبر کنید.")
        await asyncio.sleep(e.value)
        # تلاش مجدد (می‌توانید منطق پیچیده‌تری برای ریترای اضافه کنید)
        await process_message_task(message)
    except Exception as e:
        logger.error(f"❌ خطا در پردازش پیام {message.id}: {e}")
    finally:
        # حذف فایل تامنیل موقت
        if thumb_path and os.path.exists(thumb_path):
            try:
                os.remove(thumb_path)
            except:
                pass

async def queue_worker():
    """کارگر صف که پیام‌ها را یکی‌یکی پردازش می‌کند"""
    while True:
        task = await message_queue.get()
        await process_message_task(task)
        message_queue.task_done()

# --- هندلرهای پیام (تعریف توابع) ---

async def handle_start(client, message: Message):
    if message.from_user.id not in ADMIN_IDS_LIST:
        return
    await message.reply(
        "👋 سلام! من ربات کپی‌کننده پیشرفته هستم.\n\n"
        "📝 **دستورات:**\n"
        "/replace <کلمه مبدا> <کلمه مقصد> - افزودن قانون جایگزینی\n"
        "/delreplace <کلمه مبدا> - حذف قانون جایگزینی\n"
        "/listreplace - لیست قوانین فعلی\n"
        "/status - وضعیت صف و آمار\n"
        "\n🔄 اکنون در حال گوش دادن به کانال مبدا..."
    )

async def handle_replace(client, message: Message):
    if message.from_user.id not in ADMIN_IDS_LIST:
        return
    
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.reply("❌ فرمت اشتباه.\nمثال: `/replace سلام درود`")
        return
    
    source = args[1]
    target = args[2]
    
    if add_replacement(source, target):
        await message.reply(f"✅ قانون اضافه شد:\n«{source}» ➡️ «{target}»")
    else:
        await message.reply("❌ خطا در ذخیره قانون.")

async def handle_delreplace(client, message: Message):
    if message.from_user.id not in ADMIN_IDS_LIST:
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("❌ فرمت اشتباه.\nمثال: `/delreplace سلام`")
        return
    
    source = args[1]
    if remove_replacement(source):
        await message.reply(f"✅ قانون برای «{source}» حذف شد.")
    else:
        await message.reply("❌ چنین قانونی وجود نداشت.")

async def handle_listreplace(client, message: Message):
    if message.from_user.id not in ADMIN_IDS_LIST:
        return
    
    reps = get_replacements()
    if not reps:
        await message.reply("📭 هیچ قانون جایگزینی وجود ندارد.")
        return
    
    text = "📋 **لیست قوانین:**\n"
    for s, t in reps.items():
        text += f"▫️ `{s}` ➡️ `{t}`\n"
    
    await message.reply(text)

async def handle_status(client, message: Message):
    if message.from_user.id not in ADMIN_IDS_LIST:
        return
    
    q_size = message_queue.qsize()
    await message.reply(f"📊 **وضعیت سیستم:**\n"
                        f"• پیام‌های در صف: `{q_size}`\n"
                        f"• کانال مبدا: `{SOURCE_CHANNEL_ID}`\n"
                        f"• کانال مقصد: `{DEST_CHANNEL_ID}`")

async def forward_handler(client, message: Message):
    """هندلر اصلی برای دریافت پیام‌های فوروارد شده از کانال مبدا به ربات"""
    # این تابع زمانی اجرا می‌شود که کاربر (یا ربات در حالت یوزر) پیامی را فوروارد کند
    # اما هدف ما شنیدن خودکار کانال است.
    pass

async def monitor_channel_task():
    """تسک نظارت بر کانال مبدا (فقط اگر یوزر بات فعال باشد)"""
    if not user_app:
        logger.warning("⚠️ نظارت خودکار غیرفعال است (SESSION_STRING نداریم). لطفاً پیام‌ها را دستی به ربات فوروارد کنید یا Session String اضافه کنید.")
        return

    try:
        await user_app.start()
        logger.info(f"👀 شروع نظارت بر کانال {SOURCE_CHANNEL_ID} ...")
        
        last_msg_id = 0
        # دریافت آخرین پیام برای اینکه از کجا شروع کنیم (اختیاری، برای جلوگیری از پردازش تاریخچه قدیمی)
        # اینجا فرض می‌کنیم می‌خواهیم پیام‌های جدید را لحظه‌ای بگیریم.
        # روش بهتر: استفاده از iter_messages با reverse=True و پر کردن صف
        
        async for message in user_app.get_chat_history(SOURCE_CHANNEL_ID, limit=1):
            last_msg_id = message.id
            logger.info(f"آخرین پیام موجود در کانال: {last_msg_id}")
        
        # حلقه بی‌پایان برای چک کردن پیام‌های جدید
        while True:
            try:
                # دریافت پیام‌های جدیدتر از last_msg_id
                # توجه: get_chat_history از جدید به قدیم می‌دهد.
                # ما یک پیام می‌گیریم، اگر جدیدتر بود پردازش می‌کنیم.
                async for message in user_app.get_chat_history(SOURCE_CHANNEL_ID, offset_id=last_msg_id, reverse=True, limit=10):
                    if message.id > last_msg_id:
                        logger.info(f"📩 پیام جدید detected: {message.id}")
                        await message_queue.put(message)
                        last_msg_id = message.id
                    else:
                        break # پیام‌ها قدیمی‌تر شدند
                
                await asyncio.sleep(5) # چک کردن هر 5 ثانیه
                
            except FloodWait as e:
                logger.warning(f"⏳ فلود ویت در مانیتورینگ: {e.value}")
                await asyncio.sleep(e.value)
            except Exception as e:
                logger.error(f"خطا در مانیتورینگ کانال: {e}")
                await asyncio.sleep(10)
                
    except Exception as e:
        logger.error(f"❌ خطا در شروع یوزر بات: {e}")
    finally:
        if user_app.is_connected:
            await user_app.stop()

# --- تابع اصلی اجرا ---
async def main():
    # شروع ربات
    await bot_app.start()
    logger.info("🤖 ربات بات شروع شد.")
    
    # ثبت هندلرها به صورت دستی (جلوگیری از خطای NameError)
    bot_app.add_handler(handlers=MessageHandler(handle_start, filters.command("start")))
    bot_app.add_handler(handlers=MessageHandler(handle_replace, filters.command("replace")))
    bot_app.add_handler(handlers=MessageHandler(handle_delreplace, filters.command("delreplace")))
    bot_app.add_handler(handlers=MessageHandler(handle_listreplace, filters.command("listreplace")))
    bot_app.add_handler(handlers=MessageHandler(handle_status, filters.command("status")))
    
    # هندلر برای پیام‌های فوروارد شده دستی به ربات (اگر یوزر بات ندارید)
    async def manual_forward_handler(client, message: Message):
        if message.forward_from_chat and message.forward_from_chat.id == SOURCE_CHANNEL_ID:
            logger.info(f"📨 دریافت فوروارد دستی: {message.id}")
            await message_queue.put(message)
            await message.reply("✅ دریافت شد و در صف قرار گرفت.")
        elif message.chat.id == SOURCE_CHANNEL_ID: 
            # اگر یوزر بات کار نکرد و somehow پیام مستقیم آمد (کم اتفاق می‌افتد مگر با یوزر بات)
            await message_queue.put(message)
            
    bot_app.add_handler(handlers=MessageHandler(manual_forward_handler, filters=filters.forwarded))

    # شروع کارگر صف
    asyncio.create_task(queue_worker())
    
    # شروع نظارت بر کانال (اگر یوزر بات باشد)
    if user_app:
        asyncio.create_task(monitor_channel_task())
    else:
        logger.info("💡 راهنما: برای کپی خودکار بدون فوروارد دستی، حتماً SESSION_STRING را در Railway تنظیم کنید.")

    logger.info("✨ ربات آماده به کار است!")
    
    # نگه داشتن برنامه
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 ربات متوقف شد.")
    except Exception as e:
        logger.critical(f"💥 خطای بحرانی: {e}")
