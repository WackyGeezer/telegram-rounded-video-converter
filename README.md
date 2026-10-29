# Telegram Media Converter Bot 🎥🔄

A lightweight, high-performance Telegram bot that converts:
- Regular videos to **Telegram Circular Video Notes**
- Audio/music files to native **Telegram Voice Messages**
- Voice messages to **MP3 Audio files**
- Circular video notes to standard **MP4 Videos**

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/WackyGeezer/telegram-rounded-video-converter)

## Features
- Automatic 1:1 center-cropping and scaling (384x384) with standard `H.264` codec.
- High-compatibility `Opus` audio encoding strictly formatted for Telegram voice players (Mono, 48kHz, normalized timestamps).
- Internal lightweight HTTP health-check server for 24/7 cloud hosting on Render.
- Automatic zero-config FFmpeg installation via `static-ffmpeg`.
- Optional user whitelist access control (`ALLOWED_USERS`).

## Deployment on Render
1. Click the **Deploy to Render** button above.
2. Provide your `BOT_TOKEN` (from `@BotFather`).
3. (Optional) Provide `ALLOWED_USERS` (comma-separated User IDs or usernames) to restrict access.
4. Click **Apply**.
