import os
import sys
import uuid
import logging
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import static_ffmpeg
import telebot

# پیکربندی سیستم لاگ
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("TelesBot")

# خواندن متغیرهای محیطی
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    logger.error("توکن ربات (BOT_TOKEN) تنظیم نشده است!")

# لیست کاربران مجاز (آیدی‌های عددی یا یوزرنیم‌ها جدا شده با کاما)
ALLOWED_USERS_RAW = os.getenv("ALLOWED_USERS", "").strip()

bot = telebot.TeleBot(BOT_TOKEN)

# ----------------- تابع بررسی دسترسی کاربران -----------------
def is_user_allowed(user):
    """بررسی می‌کند آیا کاربر در لیست مجاز قرار دارد یا خیر"""
    if not ALLOWED_USERS_RAW:
        return True

    allowed_list = [x.strip().lower().lstrip('@') for x in ALLOWED_USERS_RAW.split(",") if x.strip()]
    if not allowed_list:
        return True

    user_id_str = str(user.id)
    username = (user.username or "").lower().lstrip('@')

    return (user_id_str in allowed_list) or (username and username in allowed_list)

def check_permission(message):
    """چک کردن دسترسی و ارسال پیام اخطار در صورت غیرمجاز بودن"""
    if not is_user_allowed(message.from_user):
        unauth_msg = (
            "⛔ **دسترسی محدود است!**\n\n"
            "این ربات خصوصی است و فقط کاربران تعیین‌شده اجازه استفاده از آن را دارند.\n\n"
            f"👤 **شناسه کاربری شما (User ID):** `{message.from_user.id}`\n"
        )
        if message.from_user.username:
            unauth_msg += f"🔹 **یوزرنیم شما:** `@{message.from_user.username}`\n"
        unauth_msg += "\nبرای دریافت دسترسی، شناسه بالا را برای مدیر ربات ارسال کنید."
        
        bot.reply_to(message, unauth_msg, parse_mode="Markdown")
        return False
    return True

# ----------------- وب‌سرور داخلی برای هلث‌چک Render -----------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Telegram Round Video & Audio Bot is running healthy!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        return

def run_health_server():
    port = int(os.getenv("PORT", 10000))
    logger.info(f"وب‌سرور هلث‌چک روی پورت {port} شروع به کار کرد.")
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        server.serve_forever()
    except Exception as e:
        logger.error(f"خطا در وب‌سرور: {e}")

# ----------------- هندلرهای ربات تلگرام -----------------
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if not check_permission(message):
        return

    welcome_text = (
        "سلام! 👋 به ربات تبدیل فایل خوش آمدید.\n\n"
        "✨ **امکانات ربات:**\n"
        "🎥 **ارسال ویدیو:** تبدیل به ویدیوی دایره‌ای (Video Note / تلس)\n"
        "🎵 **ارسال موزیک/صدا:** تبدیل به ویس تلگرام (Voice Message)\n"
        "🗣 **ارسال ویس:** تبدیل به فایل صوتی MP3\n"
        "⚪ **ارسال ویدیوی دایره‌ای:** تبدیل به ویدیوی معمولی MP4\n\n"
        "کافیست فایل مورد نظر خود را ارسال کنید!"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(commands=['myid'])
def show_id(message):
    bot.reply_to(
        message,
        f"شناسه کاربری شما (User ID): `{message.from_user.id}`\nیوزرنیم: `@{message.from_user.username}`",
        parse_mode="Markdown"
    )

@bot.message_handler(content_types=['video'])
def handle_video(message):
    if not check_permission(message):
        return
    process_video_conversion(message, message.video.file_id)

@bot.message_handler(content_types=['audio'])
def handle_audio(message):
    if not check_permission(message):
        return
    process_audio_to_voice(message, message.audio.file_id)

@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    if not check_permission(message):
        return
    process_voice_to_audio(message, message.voice.file_id)

@bot.message_handler(content_types=['video_note'])
def handle_video_note(message):
    if not check_permission(message):
        return
    process_videonote_to_video(message, message.video_note.file_id)

@bot.message_handler(content_types=['document'])
def handle_document(message):
    if not check_permission(message):
        return

    mime = (message.document.mime_type or "").lower()
    name = (message.document.file_name or "").lower()

    if mime.startswith('video/') or name.endswith(('.mp4', '.mov', '.mkv', '.avi', '.webm', '.3gp')):
        process_video_conversion(message, message.document.file_id)
    elif mime.startswith('audio/') or name.endswith(('.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.wma', '.amr')):
        process_audio_to_voice(message, message.document.file_id)
    else:
        bot.reply_to(message, "⚠️ لطفاً یک فایل ویدیویی یا صوتی معتبر ارسال کنید.")

# ----------------- توابع پردازش فایل‌ها با FFmpeg -----------------
def process_video_conversion(message, file_id):
    """تبدیل ویدیو معمولی به ویدیوی دایره‌ای (Video Note)"""
    status_msg = bot.reply_to(message, "⏳ در حال دانلود و آماده‌سازی ویدیو...")
    req_id = uuid.uuid4().hex[:8]
    input_file = f"in_vid_{req_id}.mp4"
    output_file = f"out_vid_{req_id}.mp4"

    try:
        file_info = bot.get_file(file_id)
        if file_info.file_size and file_info.file_size > 20 * 1024 * 1024:
            bot.edit_message_text("⚠️ حجم فایل بیش از ۲۰ مگابایت است.", message.chat.id, status_msg.message_id)
            return

        downloaded_bytes = bot.download_file(file_info.file_path)
        with open(input_file, 'wb') as f:
            f.write(downloaded_bytes)

        bot.edit_message_text("⚙️ در حال فشرده‌سازی و تبدیل به دایره‌ای...", message.chat.id, status_msg.message_id)

        cmd = [
            "ffmpeg", "-y", "-i", input_file,
            "-vf", "crop='min(iw,ih)':'min(iw,ih)',scale=384:384",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "25",
            "-preset", "veryfast",
            "-c:a", "aac",
            "-b:a", "64k",
            "-t", "60",
            "-movflags", "+faststart",
            output_file
        ]
        
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            logger.error(f"خطای ffmpeg: {proc.stderr.decode('utf-8', errors='ignore')}")
            raise Exception("خطا در پردازش ویدیو با ffmpeg")

        with open(output_file, 'rb') as video_note:
            bot.send_video_note(message.chat.id, video_note, reply_to_message_id=message.message_id)

        bot.delete_message(message.chat.id, status_msg.message_id)

    except Exception as e:
        logger.exception("خطا در تبدیل ویدیو")
        bot.edit_message_text(f"❌ متأسفانه خطایی رخ داد: {str(e)}", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(input_file):
            try: os.remove(input_file)
            except: pass
        if os.path.exists(output_file):
            try: os.remove(output_file)
            except: pass

def process_audio_to_voice(message, file_id):
    """تبدیل فایل صوتی / موزیک به ویس معتبر و کامپتیبل تلگرام (OGG Opus)"""
    status_msg = bot.reply_to(message, "⏳ در حال دانلود و آماده‌سازی صوت...")
    req_id = uuid.uuid4().hex[:8]
    input_file = f"in_aud_{req_id}.dat"
    output_file = f"out_voice_{req_id}.ogg"

    try:
        file_info = bot.get_file(file_id)
        if file_info.file_size and file_info.file_size > 20 * 1024 * 1024:
            bot.edit_message_text("⚠️ حجم فایل بیش از ۲۰ مگابایت است.", message.chat.id, status_msg.message_id)
            return

        downloaded_bytes = bot.download_file(file_info.file_path)
        with open(input_file, 'wb') as f:
            f.write(downloaded_bytes)

        bot.edit_message_text("⚙️ در حال تبدیل به ویس تلگرام (Voice Note)...", message.chat.id, status_msg.message_id)

        # فرمت کاملاً سازگار با پلیر ویس تلگرام:
        # ۱. -vn: حذف اجباری ویدیو/کاور تصویر که باعث خرابی هدر OGG می‌شود
        # ۲. -af asetpts=N/SR/TB: نرمال‌سازی تایم‌استمپ بسته‌ها برای رفع باگ عدم پخش و ثانیه شمار 0:00
        # ۳. -c:a libopus: کدک اختصاصی ویس
        # ۴. -b:a 48k: بیت‌ریت استاندارد
        # ۵. -ar 48000: فرکانس استاندارد اپوس
        # ۶. -ac 1: الزامی! تبدیل به مونو (تلگرام ویس استریو را پخش نمی‌کند)
        # ۷. -application voip: حالت مخصوص انتقال صدا در تلگرام
        cmd = [
            "ffmpeg", "-y", "-i", input_file,
            "-vn",
            "-af", "asetpts=N/SR/TB",
            "-c:a", "libopus",
            "-b:a", "48k",
            "-vbr", "on",
            "-compression_level", "10",
            "-ar", "48000",
            "-ac", "1",
            "-application", "voip",
            output_file
        ]
        
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            logger.error(f"خطای ffmpeg: {proc.stderr.decode('utf-8', errors='ignore')}")
            raise Exception("خطا در تبدیل فایل صوتی با ffmpeg")

        # محاسبه طول صوت بر حسب ثانیه و پاس دادن آن به تلگرام
        duration_sec = None
        try:
            probe_cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                output_file
            ]
            probe_res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if probe_res.stdout.strip():
                duration_sec = int(round(float(probe_res.stdout.strip())))
        except Exception as pe:
            logger.warning(f"عدم امکان خواندن مدت زمان ویس: {pe}")

        with open(output_file, 'rb') as voice_file:
            bot.send_voice(
                message.chat.id,
                voice_file,
                duration=duration_sec,
                reply_to_message_id=message.message_id
            )

        bot.delete_message(message.chat.id, status_msg.message_id)

    except Exception as e:
        logger.exception("خطا در تبدیل صدا به ویس")
        bot.edit_message_text(f"❌ متأسفانه خطایی رخ داد: {str(e)}", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(input_file):
            try: os.remove(input_file)
            except: pass
        if os.path.exists(output_file):
            try: os.remove(output_file)
            except: pass

def process_voice_to_audio(message, file_id):
    """تبدیل ویس به فایل صوتی MP3"""
    status_msg = bot.reply_to(message, "⏳ در حال دانلود و تبدیل ویس به MP3...")
    req_id = uuid.uuid4().hex[:8]
    input_file = f"in_voice_{req_id}.ogg"
    output_file = f"out_audio_{req_id}.mp3"

    try:
        file_info = bot.get_file(file_id)
        downloaded_bytes = bot.download_file(file_info.file_path)
        with open(input_file, 'wb') as f:
            f.write(downloaded_bytes)

        cmd = [
            "ffmpeg", "-y", "-i", input_file,
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            output_file
        ]
        subprocess.run(cmd, check=True)

        with open(output_file, 'rb') as audio_file:
            bot.send_audio(message.chat.id, audio_file, reply_to_message_id=message.message_id)

        bot.delete_message(message.chat.id, status_msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ خطا: {str(e)}", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(input_file):
            try: os.remove(input_file)
            except: pass
        if os.path.exists(output_file):
            try: os.remove(output_file)
            except: pass

def process_videonote_to_video(message, file_id):
    """تبدیل ویدیوی دایره‌ای به ویدیوی عادی MP4"""
    status_msg = bot.reply_to(message, "⏳ در حال تبدیل تلس به ویدیوی معمولی...")
    req_id = uuid.uuid4().hex[:8]
    input_file = f"in_vn_{req_id}.mp4"
    output_file = f"out_vn_{req_id}.mp4"

    try:
        file_info = bot.get_file(file_id)
        downloaded_bytes = bot.download_file(file_info.file_path)
        with open(input_file, 'wb') as f:
            f.write(downloaded_bytes)

        cmd = [
            "ffmpeg", "-y", "-i", input_file,
            "-c", "copy",
            output_file
        ]
        subprocess.run(cmd, check=True)

        with open(output_file, 'rb') as vid_file:
            bot.send_video(message.chat.id, vid_file, reply_to_message_id=message.message_id)

        bot.delete_message(message.chat.id, status_msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ خطا: {str(e)}", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(input_file):
            try: os.remove(input_file)
            except: pass
        if os.path.exists(output_file):
            try: os.remove(output_file)
            except: pass

# ----------------- تابع اصلی اجرای برنامه -----------------
def main():
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    logger.info("در حال بارگذاری و تنظیم ffmpeg...")
    static_ffmpeg.add_paths()

    if not BOT_TOKEN:
        logger.error("متغیر BOT_TOKEN خالی است!")
        sys.exit(1)

    try:
        logger.info("بررسی و حذف وب‌هوک‌های قبلی...")
        bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logger.warning(f"عدم امکان حذف وبهوک: {e}")

    logger.info("ربات با موفقیت روشن شد و در حال پاسخ‌گویی است...")
    bot.infinity_polling(skip_pending=True)

if __name__ == "__main__":
    main()
