import os
import sys
import uuid
import logging
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import static_ffmpeg
import telebot

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("ConverterBot")

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    logger.error("BOT_TOKEN environment variable is not set!")

# Whitelisted users (comma-separated IDs or usernames)
# Example: "123456789, @username, 987654321"
ALLOWED_USERS_RAW = os.getenv("ALLOWED_USERS", "").strip()

bot = telebot.TeleBot(BOT_TOKEN)

# ----------------- Access Control -----------------
def is_user_allowed(user):
    """Checks if the user is in the whitelist"""
    if not ALLOWED_USERS_RAW:
        return True

    allowed_list = [x.strip().lower().lstrip('@') for x in ALLOWED_USERS_RAW.split(",") if x.strip()]
    if not allowed_list:
        return True

    user_id_str = str(user.id)
    username = (user.username or "").lower().lstrip('@')

    return (user_id_str in allowed_list) or (username and username in allowed_list)

def check_permission(message):
    """Enforces whitelist check and replies if unauthorized"""
    if not is_user_allowed(message.from_user):
        unauth_msg = (
            "⛔ **Access Denied!**\n\n"
            "This bot is private and only authorized users are permitted to use it.\n\n"
            f"👤 **Your User ID:** `{message.from_user.id}`\n"
        )
        if message.from_user.username:
            unauth_msg += f"🔹 **Your Username:** `@{message.from_user.username}`\n"
        unauth_msg += "\nTo request access, please send your User ID to the bot administrator."

        bot.reply_to(message, unauth_msg, parse_mode="Markdown")
        return False
    return True

# ----------------- Internal Health Check Web Server -----------------
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
    logger.info(f"Health check server running on port {port}.")
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        server.serve_forever()
    except Exception as e:
        logger.error(f"Error in health server: {e}")

# ----------------- Telegram Handlers -----------------
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if not check_permission(message):
        return

    welcome_text = (
        "Hello! 👋 Welcome to the **Media Converter Bot**.\n\n"
        "✨ **Features:**\n"
        "🎥 **Send Video:** Convert to Telegram Round Video (Video Note)\n"
        "🎵 **Send Audio / Music:** Convert to Telegram Voice Message\n"
        "🗣 **Send Voice Message:** Convert to MP3 Audio file\n"
        "⚪ **Send Video Note:** Convert to standard MP4 Video\n\n"
        "Simply send your file to get started!"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(commands=['myid'])
def show_id(message):
    bot.reply_to(
        message,
        f"👤 **User ID:** `{message.from_user.id}`\n🔹 **Username:** `@{message.from_user.username}`",
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
        bot.reply_to(message, "⚠️ Please send a valid audio or video file.")

# ----------------- FFmpeg Processing Functions -----------------
def process_video_conversion(message, file_id):
    """Converts regular video to 1:1 round video note"""
    status_msg = bot.reply_to(message, "⏳ Downloading and preparing video...")
    req_id = uuid.uuid4().hex[:8]
    input_file = f"in_vid_{req_id}.mp4"
    output_file = f"out_vid_{req_id}.mp4"

    try:
        file_info = bot.get_file(file_id)
        if file_info.file_size and file_info.file_size > 20 * 1024 * 1024:
            bot.edit_message_text(
                "⚠️ File exceeds 20 MB. Telegram bots cannot download files larger than 20 MB directly.",
                message.chat.id,
                status_msg.message_id
            )
            return

        downloaded_bytes = bot.download_file(file_info.file_path)
        with open(input_file, 'wb') as f:
            f.write(downloaded_bytes)

        bot.edit_message_text("⚙️ Cropping and converting to round video...", message.chat.id, status_msg.message_id)

        # Crop to square 1:1 (384x384) with H.264
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
            logger.error(f"FFmpeg error: {proc.stderr.decode('utf-8', errors='ignore')}")
            raise Exception("Failed to process video with FFmpeg.")

        with open(output_file, 'rb') as video_note:
            bot.send_video_note(message.chat.id, video_note, reply_to_message_id=message.message_id)

        bot.delete_message(message.chat.id, status_msg.message_id)

    except Exception as e:
        logger.exception("Error during video conversion")
        bot.edit_message_text(f"❌ Error: {str(e)}", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(input_file):
            try: os.remove(input_file)
            except: pass
        if os.path.exists(output_file):
            try: os.remove(output_file)
            except: pass

def process_audio_to_voice(message, file_id):
    """Converts audio/music to Telegram compatible voice note (OGG Opus)"""
    status_msg = bot.reply_to(message, "⏳ Downloading and preparing audio...")
    req_id = uuid.uuid4().hex[:8]
    input_file = f"in_aud_{req_id}.dat"
    output_file = f"out_voice_{req_id}.ogg"

    try:
        file_info = bot.get_file(file_id)
        if file_info.file_size and file_info.file_size > 20 * 1024 * 1024:
            bot.edit_message_text(
                "⚠️ File exceeds 20 MB. Telegram bots cannot download files larger than 20 MB directly.",
                message.chat.id,
                status_msg.message_id
            )
            return

        downloaded_bytes = bot.download_file(file_info.file_path)
        with open(input_file, 'wb') as f:
            f.write(downloaded_bytes)

        bot.edit_message_text("⚙️ Converting to Telegram Voice Message...", message.chat.id, status_msg.message_id)

        # Standard Telegram voice note recipe:
        # -vn: strip cover art/video streams
        # -af asetpts=N/SR/TB: normalize packet timestamps
        # -ac 1: force mono
        # -ar 48000: 48kHz sample rate
        # -application voip: voice profile
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
            logger.error(f"FFmpeg error: {proc.stderr.decode('utf-8', errors='ignore')}")
            raise Exception("Failed to process audio with FFmpeg.")

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
            logger.warning(f"Could not read voice duration: {pe}")

        with open(output_file, 'rb') as voice_file:
            bot.send_voice(
                message.chat.id,
                voice_file,
                duration=duration_sec,
                reply_to_message_id=message.message_id
            )

        bot.delete_message(message.chat.id, status_msg.message_id)

    except Exception as e:
        logger.exception("Error during audio conversion")
        bot.edit_message_text(f"❌ Error: {str(e)}", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(input_file):
            try: os.remove(input_file)
            except: pass
        if os.path.exists(output_file):
            try: os.remove(output_file)
            except: pass

def process_voice_to_audio(message, file_id):
    """Converts voice note to MP3 audio file"""
    status_msg = bot.reply_to(message, "⏳ Downloading and converting voice to MP3...")
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
        bot.edit_message_text(f"❌ Error: {str(e)}", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(input_file):
            try: os.remove(input_file)
            except: pass
        if os.path.exists(output_file):
            try: os.remove(output_file)
            except: pass

def process_videonote_to_video(message, file_id):
    """Converts round video note to standard MP4 video"""
    status_msg = bot.reply_to(message, "⏳ Converting video note to MP4...")
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
        bot.edit_message_text(f"❌ Error: {str(e)}", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(input_file):
            try: os.remove(input_file)
            except: pass
        if os.path.exists(output_file):
            try: os.remove(output_file)
            except: pass

# ----------------- Main Entrypoint -----------------
def main():
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    logger.info("Configuring FFmpeg...")
    static_ffmpeg.add_paths()

    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is empty!")
        sys.exit(1)

    try:
        logger.info("Clearing any existing webhooks...")
        bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logger.warning(f"Failed to clear webhook: {e}")

    logger.info("Bot is active and polling for updates...")
    bot.infinity_polling(skip_pending=True)

if __name__ == "__main__":
    main()
