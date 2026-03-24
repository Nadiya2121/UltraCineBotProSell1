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

# --- আপনার TMDB API Key এখানে বসান ---
MY_TMDB_API_KEY = "আপনার_টিএমডিবি_এপিআই_কি_এখানে_দিন"

CAPTION_LANGUAGES = ["Bhojpuri", "Hindi", "Bengali", "Tamil", "English", "Bangla", "Telugu", "Malayalam", "Kannada", "Marathi", "Punjabi", "Bengoli", "Gujrati", "Korean", "Gujarati", "Spanish", "French", "German", "Chinese", "Arabic", "Portuguese", "Russian", "Japanese", "Odia", "Assamese", "Urdu"]

DEFAULT_IMAGE_URL = "https://te.legra.ph/file/88d845b4f8a024a71465d.jpg"

SILENTX_PREMIUM_UPDATE = """
<blockquote>🎬 𝕻ℝ𝔼𝕄𝕀𝕌𝕄 𝕄𝕆𝕍氷 𝕌ℙ𝔻𝔸𝕋𝔼 🎥</blockquote>

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

<b>⚡ Powered By @TGLinkBase</b>
"""

notified_movies = set()
media_filter = filters.document | filters.video | filters.audio
media_process_lock = asyncio.Lock()

# --- সরাসরি TMDB থেকে লম্বা পোস্টার এবং তথ্য আনার ফাংশন ---
async def get_tmdb_details_local(title: str, year: str = None) -> Optional[Dict[str, Any]]:
    try:
        async with aiohttp.ClientSession() as session:
            # সার্চ করা হচ্ছে
            search_url = f"https://api.themoviedb.org/3/search/multi"
            params = {"api_key": MY_TMDB_API_KEY, "query": title}
            if year: params["year"] = year

            async with session.get(search_url, params=params) as resp:
                if resp.status != 200: return None
                results = await resp.json()
                if not results.get("results"): return None
                
                res = results["results"][0]
                m_type = res.get("media_type", "movie")
                tmdb_id = res.get("id")

                # বিস্তারিত তথ্য এবং ট্রেইলার আনার জন্য
                detail_url = f"https://api.themoviedb.org/3/{m_type}/{tmdb_id}"
                async with session.get(detail_url, params={"api_key": MY_TMDB_API_KEY, "append_to_response": "videos,credits"}) as det_resp:
                    if det_resp.status != 200: return None
                    full_data = await det_resp.json()

                # ডিরেক্টর বের করার লজিক
                director = "N/A"
                if m_type == "movie":
                    for crew in full_data.get("credits", {}).get("crew", []):
                        if crew["job"] == "Director":
                            director = crew["name"]
                            break
                else:
                    if full_data.get("created_by"):
                        director = full_data["created_by"][0]["name"]

                # লম্বা পোস্টার লিঙ্ক (Portrait)
                poster_path = full_data.get("poster_path")
                poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else DEFAULT_IMAGE_URL

                return {
                    "title": full_data.get("title") or full_data.get("name"),
                    "kind": m_type.upper(),
                    "director": director,
                    "release_date": full_data.get("release_date") or full_data.get("first_air_date", "TBA"),
                    "vote_average": f"{full_data.get('vote_average', 0):.1f}",
                    "vote_count": f"{full_data.get('vote_count', 0):,}",
                    "genres": [g["name"] for g in full_data.get("genres", [])],
                    "poster_url": poster_url,
                    "videos": [{"url": f"https://www.youtube.com/watch?v={v['key']}"} for v in full_data.get("videos", {}).get("results", []) if v['site'] == 'YouTube']
                }
    except Exception as e:
        LOGGER.error(f"TMDB Local Fetch Error: {e}")
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
            if success and silentxbotz == 1 and await get_status(bot.me.id):            
                await send_movie_update(bot, file_name=media.file_name, caption=media.caption)
                
        except Exception as e:
            LOGGER.error(f"Error while saving media: {e}")

async def send_movie_update(bot, file_name, caption):
    try:
        file_name = clean_filename(file_name)
        caption = clean_filename(caption)
        
        year_match = re.search(r"\b(19|20)\d{2}\b", caption)
        year = year_match.group(0) if year_match else None      
        
        language = await get_languages(caption) or "Multi-Audio"      
        
        # এখানে বাইরের fetch_tmdb_data এর বদলে এই ফাইলের নিজস্ব ফাংশন ব্যবহার করা হয়েছে
        tmdb_data = await get_tmdb_details_local(file_name, year)
        if not tmdb_data: return 

        if tmdb_data["title"] in notified_movies: return 
        notified_movies.add(tmdb_data["title"])      

        search_movie = tmdb_data["title"].replace(" ", "-")
        
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
        await send_with_visual(bot, full_caption, tmdb_data, search_movie)        
    except Exception as e:
        LOGGER.error(f"Error In Movie Update: {e}")

def escape_html(text: str) -> str:
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;') if text else ""

def get_trailer_button(tmdb_data: Dict) -> list:
    videos = tmdb_data.get("videos", [])
    if videos:
        return [InlineKeyboardButton("▶️ Watch Trailer", url=videos[0]["url"])]
    return []
    
async def send_with_visual(bot, caption: str, tmdb_data: Dict, search_movie):
    try:
        # এখানে সরাসরি আমাদের পাওয়া লম্বা পোস্টার URL ব্যবহার করা হচ্ছে
        visual_url = tmdb_data.get("poster_url")
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

async def get_languages(text: str) -> str:
    found_langs = [lang for lang in CAPTION_LANGUAGES if lang.lower().replace(" ", "") in text.lower().replace(" ", "")]
    return ", ".join(found_langs[:2]) if found_langs else "Multi-Audio"

async def get_qualities(text): 
    qualities = ["ORG", "hdcam", "HDRip", "WEB-DL", "DVDrip", "HDTC"]
    return ", ".join([q for q in qualities if q.lower() in text.lower()])

async def get_pixels(caption):
    pixels = ["480p", "720p", "1080p", "2160p", "4K"]
    return ", ".join([p for p in pixels if p.lower() in caption.lower()])
