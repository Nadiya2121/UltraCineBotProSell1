import re
import io
import math
import random
import string
import aiohttp
import asyncio
import hashlib
import requests
from info import *
from utils import *
from utils import clean_filename
from logging_helper import LOGGER
from typing import Optional, Dict, Any
from datetime import datetime
from pyrogram import Client, filters
from database.ia_filterdb import save_file
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode

# --- TMDB API Config ---
MY_TMDB_API_KEY = "7dc544d9253bccc3cfecc1c677f69819"

CAPTION_LANGUAGES = ["Bhojpuri", "Hindi", "Bengali", "Tamil", "English", "Bangla", "Telugu", "Malayalam", "Kannada", "Marathi", "Punjabi", "Bengoli", "Gujrati", "Korean", "Gujarati", "Spanish", "French", "German", "Chinese", "Arabic", "Portuguese", "Russian", "Japanese", "Odia", "Assamese", "Urdu"]

DEFAULT_IMAGE_URL = "https://te.legra.ph/file/88d845b4f8a024a71465d.jpg"

SILENTX_PREMIUM_UPDATE = """
<blockquote>🎬 𝕻ℝ𝔼𝕄𝕀𝕌𝕄 𝕄𝕆𝕍𝕀𝔼 𝕌ℙ𝔻𝔸𝕋𝔼 🎥</blockquote>

<b><u>{}</u></b> <code>#{}</code>

<code>━━━━━━━━━━━━━━━━━━</code>
<b>🔈 Audio</b>: {}
<b>📺 Format</b>: {}

<code>━━━━━━━━━━━━━━━━━━</code>
<b>🎭 Director</b>: {}
<b>📅 Release</b>: {}
<b>⭐ IMDb</b>: {}/10 (<code>{}</code> votes)
<b>🏷️ Genres</b>: {}
<code>━━━━━━━━━━━━━━━━━━</code>

<b>⚡ Powered By @SilentXBotz</b>
"""

media_filter = filters.document | filters.video | filters.audio
media_process_lock = asyncio.Lock()

# --- TMDB Fetching Logic ---
async def local_tmdb_fetch(title: str, year: str = None):
    try:
        # টাইটেল ক্লিন করা (Chokro S01 E11 -> Chokro)
        search_title = re.sub(r'(?i)(?:s|season|e|episode|ep)\s*\d+|[^a-zA-Z0-9\s]', '', title).split('20')[0].strip()
        
        async with aiohttp.ClientSession() as session:
            url = f"https://api.themoviedb.org/3/search/multi?api_key={MY_TMDB_API_KEY}&query={search_title}"
            if year: url += f"&year={year}"
            
            async with session.get(url) as resp:
                data = await resp.json()
                if not data.get("results"): return None
                
                res = data["results"][0]
                m_type = res.get("media_type", "movie")
                
                # বিস্তারিত তথ্য
                detail_url = f"https://api.themoviedb.org/3/{m_type}/{res['id']}?api_key={MY_TMDB_API_KEY}&append_to_response=videos"
                async with session.get(detail_url) as det_resp:
                    full_data = await det_resp.json()
                    
                    return {
                        "title": full_data.get("title") or full_data.get("name"),
                        "kind": m_type.upper(),
                        "release_date": full_data.get("release_date") or full_data.get("first_air_date", "TBA"),
                        "vote_average": f"{full_data.get('vote_average', 0):.1f}",
                        "vote_count": f"{full_data.get('vote_count', 0):,}",
                        "genres": [g["name"] for g in full_data.get("genres", [])],
                        "poster_url": f"https://image.tmdb.org/t/p/w500{full_data.get('poster_path')}" if full_data.get('poster_path') else DEFAULT_IMAGE_URL,
                        "director": "N/A", # ডিরেক্টর বের করার জন্য আলাদা লুপ লাগে, সংক্ষেপ করা হলো
                        "videos": [{"url": f"https://youtube.com/watch?v={v['key']}"} for v in full_data.get("videos", {}).get("results", []) if v['site'] == 'YouTube']
                    }
    except:
        return None

@Client.on_message(filters.chat(CHANNELS) & media_filter)
async def media(bot, message):
    for file_type in ("document", "video", "audio"):
        media = getattr(message, file_type, None)
        if media is not None:
            break
    else:
        return

    media.file_type = file_type
    media.caption = message.caption

    async with media_process_lock:
        try:
            success, silentxbotz = await save_file(media)
            # 'silentxbotz == 1' শর্তটি তুলে দেওয়া হয়েছে যাতে পুরোনো ফাইলও পোস্ট হয়
            if success and await get_status(bot.me.id):            
                await send_movie_update(bot, file_name=media.file_name, caption=media.caption)
                
        except Exception as e:
            LOGGER.error(f"Error in media handler: {e}")

async def send_movie_update(bot, file_name, caption):
    try:
        clean_name = clean_filename(file_name)
        year_match = re.search(r"\b(19|20)\d{2}\b", caption or file_name)
        year = year_match.group(0) if year_match else None      
        
        language = await get_languages(caption or file_name)
        
        # TMDB থেকে ডাটা আনা
        tmdb_data = await local_tmdb_fetch(clean_name, year)
        if not tmdb_data:
            LOGGER.info(f"TMDB data not found for: {clean_name}")
            return 

        full_caption = SILENTX_PREMIUM_UPDATE.format(
            escape_html(tmdb_data["title"]),
            tmdb_data["kind"],
            escape_html(language),
            "MKV" if "mkv" in file_name.lower() else "MP4",
            escape_html(tmdb_data["director"]),
            escape_html(tmdb_data["release_date"]),
            tmdb_data["vote_average"],
            tmdb_data["vote_count"],
            escape_html(", ".join(tmdb_data["genres"][:3]))
        )        
        
        await send_with_visual(bot, full_caption, tmdb_data, tmdb_data["title"].replace(" ", "-"))        
    except Exception as e:
        LOGGER.error(f"Error In Movie Update: {e}")

async def send_with_visual(bot, caption: str, tmdb_data: Dict, search_movie):
    try:
        visual_url = tmdb_data.get("poster_url", DEFAULT_IMAGE_URL)
        get_file = f'https://telegram.me/{temp.U_NAME}?start=getfile-{search_movie}'
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 Get File", url=get_file)],
            get_trailer_button(tmdb_data)
        ])
        
        await bot.send_photo(
            chat_id=MOVIE_UPDATE_CHANNEL, 
            photo=visual_url, 
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    except Exception as e:
        LOGGER.error(f"Visual Send Error: {e}")

def get_trailer_button(tmdb_data: Dict) -> list:
    videos = tmdb_data.get("videos", [])
    if videos:
        return [InlineKeyboardButton("▶️ Watch Trailer", url=videos[0]["url"])]
    return []

def escape_html(text: str) -> str:
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;') if text else ""

async def get_languages(text: str) -> str:
    found_langs = [lang for lang in CAPTION_LANGUAGES if lang.lower() in text.lower()]
    return ", ".join(found_langs[:2]) if found_langs else "Multi-Audio"
