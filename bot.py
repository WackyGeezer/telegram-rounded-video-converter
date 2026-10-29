import os
import sys
import uuid
import logging
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import static_ffmpeg
import telebot

# پیکربندی لاگ‌ها
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("TelesBot")

# افزودن خودکار ffmpeg به متغیرهای سیستمی PATH
logger.info("در حال تنظیم ffmpeg...")
static_ffmpeg.add_paths()

# خواندن توکن از محیط یا متغیر پیش‌فرض
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    logger.warning("توکن ربات (BOT_TOKEN) تنظیم نشده است!")

bot = telebot.TeleBot(BOT_TOKEN)

# ----------------- وب‌سرور داخلی برای هلث‌چک Render -----------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Telegram Round Video Bot is running healthy!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        # جلوگیری از شلوغی لاگ‌ها توسط پینگ‌های مکرر
        return

def run_health_server():
    port = int(os.getenv("PORT", 10000))
    logger.info(f"وب‌سرور هلث‌چک روی پورت {port} شروع به کار کرد.")
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# ----------------- هندلرهای تلگرام -----------------
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "سلام! 👋\n\n"
        "من ربات تبدیل ویدیو به **ویدیوی دایره‌ای (Video Note / تلس)** هستم.\n\n"
        "کافیست یک ویدیو (یا فایل ویدیویی) برای من بفرستید تا در چند ثانیه آن را به ویدیوی گرد تلگرام تبدیل کنم! 🎥✨"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(content_types=['video', 'document'])
def handle_video(message):
    # بررسی نوع فایل
    file_id = None
    if message.content_type == 'video':
        file_id = message.video.file_id
    elif message.document:
        mime = message.document.mime_type or ""
        name = message.document.file_name or ""
        if mime.startswith('video/') or name.lower().endswith(('.mp4', '.mov', '.mkv', '.avi', '.webm')):
            file_id = message.document.file_id

    if not file_id:
        return

    status_msg = bot.reply_to(message, "⏳ در حال دانلود و آماده‌سازی ویدیو...")

    # نام‌گذاری یکتا برای جلوگیری از تداخل درخواست‌های همزمان
    req_id = uuid.uuid4().hex[:8]
    input_file = f"temp_in_{req_id}.mp4"
    output_file = f"temp_out_{req_id}.mp4"

    try:
        # ۱. دانلود فایل ویدیو
        file_info = bot.get_file(file_id)
        if file_info.file_size and file_info.file_size > 20 * 1024 * 1024:
            bot.edit_message_text("⚠️ حجم فایل بیش از ۲۰ مگابایت است. ربات‌های تلگرام به دلیل محدودیت تلگرام فقط تا ۲۰ مگابایت فایل مستقیم دریافت می‌کنند.", message.chat.id, status_msg.message_id)
            return

        downloaded_bytes = bot.download_file(file_info.file_path)
        with open(input_file, 'wb') as f:
            f.write(downloaded_bytes)

        bot.edit_message_text("⚙️ در حال فشرده‌سازی و تبدیل به دایره‌ای...", message.chat.id, status_msg.message_id)

        # ۲. تبدیل ویدیو با ffmpeg به نسبت ۱:۱ و ابعاد ۳۸۴x۳۸۴ استاندارد تلگرام
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
            raise Exception("خطا در پردازش فایل ویدیویی با ffmpeg")

        # ۳. ارسال به صورت Video Note (تلس تلگرام)
        with open(output_file, 'rb') as video_note:
            bot.send_video_note(message.chat.id, video_note, reply_to_message_id=message.message_id)

        bot.delete_message(message.chat.id, status_msg.message_id)

    except Exception as e:
        logger.exception("خطا در پردازش ویدیو")
        bot.edit_message_text(f"❌ متأسفانه خطایی رخ داد: {str(e)}", message.chat.id, status_msg.message_id)

    finally:
        # حذف فایل‌های موقت
        if os.path.exists(input_file):
            try: os.remove(input_file)
            except: pass
        if os.path.exists(output_file):
            try: os.remove(output_file)
            except: pass

# ----------------- تابع اصلی اجرای برنامه -----------------
def main():
    if not BOT_TOKEN:
        logger.error("لطفاً توکن ربات را در متغیر محیطی BOT_TOKEN قرار دهید.")
        sys.exit(1)

    # راه‌اندازی سرور هلث‌چک در یک رشته (Thread) جداگانه
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    logger.info("ربات تلگرام با موفقیت روشن شد و در حال پولینگ است...")
    bot.infinity_polling(skip_pending=True)

if __name__ == "__main__":
    main()
