#!/usr/bin/env python3
"""
YouLearn Telegram Bot - YouTube Video Transcription and Summarization Bot
Integrates the YouLearn functionality with a Telegram bot interface.
"""

import os
import logging
import tempfile
from pathlib import Path
from typing import Optional, Literal
import time
import random
from functools import wraps
import asyncio
import platform
import sys

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import yt_dlp
import re
import requests
from tqdm import tqdm
import dotenv
from openai import OpenAI
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

# Semafori per limitare le richieste concorrenti
TRANSCRIPT_SEMAPHORE = asyncio.Semaphore(5)  # Max 5 richieste di trascrizione simultanee
SUMMARY_SEMAPHORE = asyncio.Semaphore(3)     # Max 3 richieste di riassunto simultanee
GLOBAL_REQUEST_SEMAPHORE = asyncio.Semaphore(5)  # Limite di richieste globali simultanee
BUTTON_CALLBACK_TIMEOUT = 180.0  # Timeout per operazioni dei callback in secondi

# Load environment variables
dotenv.load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Create output directory if it doesn't exist
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

# Get API keys from environment variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# Whitelist configuration
ALLOWED_USERS = os.getenv("ALLOWED_USERS", "")

def is_user_allowed(user_id: int) -> bool:
    """Check if a user is allowed to use the bot based on their Telegram ID."""
    if not ALLOWED_USERS:
        logger.warning("ALLOWED_USERS environment variable is not set. No users are allowed.")
        return False
        
    try:
        allowed_ids = [int(id.strip()) for id in ALLOWED_USERS.split(",") if id.strip()]
        return user_id in allowed_ids
    except ValueError as e:
        logger.error(f"Error parsing ALLOWED_USERS: {e}")
        return False

# Funzione di utilità per gestire semafori con timeout in modo compatibile con Python 3.10
async def acquire_semaphore_with_timeout(semaphore, timeout):
    """Acquisisce un semaforo con timeout in modo compatibile con Python 3.10."""
    try:
        async def _acquire():
            await semaphore.acquire()
            return True
            
        return await asyncio.wait_for(_acquire(), timeout=timeout)
    except asyncio.TimeoutError:
        return False

def extract_video_id(url: str) -> Optional[str]:
    """Extract the video ID from a YouTube URL."""
    patterns = [
        r'(?:v=|\/videos\/|embed\/|youtu.be\/|\/v\/|\/e\/|watch\?v=|&v=)([^#\&\?\n]{11})',
        r'(?:shorts\/)([^#\&\?\/\n]{11})'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    logger.warning(f"Could not extract video ID from URL: {url}")
    return None

def get_video_title(video_id: str) -> str:
    """Get the title of a YouTube video using yt-dlp."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            return info.get('title', f"Video {video_id}")
    except Exception as e:
        logger.error(f"Error getting video title: {e}")
        return f"Video {video_id}"

async def get_transcript_from_youtube(video_id: str) -> Optional[str]:
    """Get video transcript directly from YouTube."""
    async with TRANSCRIPT_SEMAPHORE:
        try:
            # Try with specific languages first
            try:
                transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['en', 'it'])
                return ' '.join([item['text'] for item in transcript_list])
            except (NoTranscriptFound, TranscriptsDisabled):
                # Try with auto-detection
                transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
                return ' '.join([item['text'] for item in transcript_list])
                
        except Exception as e:
            logger.error(f"Error retrieving transcript: {e}")
            return None

async def summarize_with_ai(transcript: str, video_title: str, service: Literal["openai", "deepseek"] = "openai") -> Optional[str]:
    """Generate a summary using AI services."""
    async with SUMMARY_SEMAPHORE:
        try:
            system_prompt = "You are an expert at summarizing video content in Italian. Create a comprehensive summary of the following video transcript."
            user_prompt = f"Title: {video_title}\n\nTranscript:\n{transcript}\n\nPlease provide a detailed summary of this video's content, highlighting the main points, key insights, and important details."
            
            if service == "openai":
                if not OPENAI_API_KEY:
                    return None
                    
                client = OpenAI(api_key=OPENAI_API_KEY)
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    max_tokens=1500,
                    temperature=0.5,
                )
                
            elif service == "deepseek":
                if not DEEPSEEK_API_KEY:
                    return None
                    
                client = OpenAI(
                    api_key=DEEPSEEK_API_KEY,
                    base_url="https://api.deepseek.com"
                )
                response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    max_tokens=1500,
                    temperature=0.5,
                )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    if not is_user_allowed(update.effective_user.id):
        await update.message.reply_text(
            "❌ Non sei autorizzato ad utilizzare questo bot.\n\n"
            f"Il tuo Telegram ID è: {update.effective_user.id}"
        )
        return
        
    welcome_message = (
        "👋 Ciao! Sono YouLearn Bot.\n\n"
        "Inviami il link di un video YouTube e ti aiuterò a:\n"
        "📝 Ottenere la trascrizione del video\n"
        "📚 Generare un riassunto del contenuto\n\n"
        "Prova ora - invia un link YouTube!"
    )
    await update.message.reply_text(welcome_message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    if not is_user_allowed(update.effective_user.id):
        await update.message.reply_text(
            "❌ Non sei autorizzato ad utilizzare questo bot.\n\n"
            f"Il tuo Telegram ID è: {update.effective_user.id}"
        )
        return
        
    help_text = (
        "🔍 Come usare YouLearn Bot:\n\n"
        "1. Invia il link di un video YouTube\n"
        "2. Scegli se vuoi:\n"
        "   📝 La trascrizione del video\n"
        "   📚 Un riassunto del contenuto\n\n"
        "❗ Note:\n"
        "- La trascrizione può richiedere qualche minuto\n"
        "- Il riassunto viene generato usando AI\n"
        "- Supporta video standard e Shorts"
    )
    await update.message.reply_text(help_text)

async def process_youtube_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process a YouTube URL and show action buttons."""
    if not is_user_allowed(update.effective_user.id):
        await update.message.reply_text(
            "❌ Non sei autorizzato ad utilizzare questo bot.\n\n"
            f"Il tuo Telegram ID è: {update.effective_user.id}"
        )
        return
        
    url = update.message.text
    video_id = extract_video_id(url)
    
    if not video_id:
        await update.message.reply_text(
            "❌ Link non valido. Per favore, invia un link YouTube valido."
        )
        return
    
    context.user_data['video_id'] = video_id
    
    keyboard = [
        [
            InlineKeyboardButton("📝 Trascrizione", callback_data='transcript'),
            InlineKeyboardButton("📚 Riassunto", callback_data='summary_choice')
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🎥 Cosa vuoi fare con questo video?", reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button presses."""
    query = update.callback_query
    user_id = update.effective_user.id
    
    if not is_user_allowed(user_id):
        await query.answer("❌ Non sei autorizzato ad utilizzare questo bot.", show_alert=True)
        return

    await query.answer()
    
    video_id = context.user_data.get('video_id')
    if not video_id:
        await query.edit_message_text("❌ Sessione scaduta. Invia nuovamente il link YouTube.")
        return
    
    if query.data == 'summary_choice':
        keyboard = [
            [
                InlineKeyboardButton("📚 OpenAI", callback_data='summary_openai'),
                InlineKeyboardButton("📚 Deepseek", callback_data='summary_deepseek')
            ],
            [InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "Scegli il servizio per il riassunto:",
            reply_markup=reply_markup
        )
        return

    if query.data == 'back_to_main':
        keyboard = [
            [
                InlineKeyboardButton("📝 Trascrizione", callback_data='transcript'),
                InlineKeyboardButton("📚 Riassunto", callback_data='summary_choice')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("🎥 Cosa vuoi fare con questo video?", reply_markup=reply_markup)
        return

    try:
        acquired = await acquire_semaphore_with_timeout(GLOBAL_REQUEST_SEMAPHORE, 5.0)
        if not acquired:
            await query.edit_message_text(
                "⏳ Troppe richieste in corso. Riprova fra qualche secondo...",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]])
            )
            return
        
        try:
            await query.edit_message_text("⏳ Elaborazione in corso...")
            await asyncio.wait_for(
                process_request(query, context, video_id),
                timeout=BUTTON_CALLBACK_TIMEOUT
            )
        except asyncio.TimeoutError:
            await query.edit_message_text(
                "⏰ L'operazione sta impiegando troppo tempo ed è stata interrotta.\n"
                "Riprova più tardi o con un altro video.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]])
            )
        finally:
            GLOBAL_REQUEST_SEMAPHORE.release()
            
    except Exception as e:
        logger.error(f"Error processing request: {e}")
        await query.edit_message_text(
            "❌ Si è verificato un errore durante l'elaborazione della richiesta.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]])
        )

async def process_request(query, context, video_id):
    """Process transcript or summary request."""
    try:
        video_title = get_video_title(video_id)
        transcript = await get_transcript_from_youtube(video_id)
        
        if transcript is None:
            await query.edit_message_text(
                "❌ Non è stato possibile ottenere la trascrizione.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]])
            )
            return

        if query.data == 'transcript':
            chunks = [transcript[i:i+4000] for i in range(0, len(transcript), 4000)]
            for i, chunk in enumerate(chunks):
                if i == 0:
                    header = f"📝 Trascrizione: {video_title}\n\n"
                    await query.message.reply_text(header + chunk)
                else:
                    await query.message.reply_text(chunk)
            await query.edit_message_text(
                "✅ Trascrizione completata!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]])
            )

        elif query.data in ['summary_openai', 'summary_deepseek']:
            service = "openai" if query.data == 'summary_openai' else "deepseek"
            
            if (service == "openai" and not OPENAI_API_KEY) or (service == "deepseek" and not DEEPSEEK_API_KEY):
                await query.edit_message_text(
                    f"❌ {service.upper()} API key non configurata. Contatta l'amministratore del bot.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]])
                )
                return

            await query.edit_message_text(f"⏳ Generazione riassunto con {service.upper()} in corso...")
            summary = await summarize_with_ai(transcript, video_title, service)
            
            if summary:
                service_name = "OpenAI (gpt-4o-mini)" if service == "openai" else "Deepseek"
                response = f"📚 Riassunto ({service_name}): {video_title}\n\n{summary}"
                
                if len(response) > 4000:
                    chunks = [response[i:i+4000] for i in range(0, len(response), 4000)]
                    for chunk in chunks:
                        await query.message.reply_text(chunk)
                else:
                    await query.message.reply_text(response)
                
                await query.edit_message_text(
                    f"✅ Riassunto con {service_name} completato!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]])
                )
            else:
                await query.edit_message_text(
                    f"❌ Non è stato possibile generare il riassunto con {service}.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]])
                )
                
    except Exception as e:
        logger.error(f"Error in process_request: {e}")
        raise

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log Errors caused by Updates."""
    logger.error(f"Update {update} caused error {context.error}")
    
    if update and update.effective_message:
        error_msg = str(context.error).lower()
        
        if isinstance(context.error, asyncio.TimeoutError) or "timed out" in error_msg:
            await update.effective_message.reply_text(
                "⏰ L'operazione ha richiesto troppo tempo ed è stata interrotta.\n"
                "Riprova più tardi o con un video più breve.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]])
            )
        else:
            await update.effective_message.reply_text(
                "❌ Si è verificato un errore durante l'elaborazione della richiesta.\n"
                "Per favore, riprova più tardi.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]])
            )

def main() -> None:
    """Start the bot."""
    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_youtube_url))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_error_handler(error_handler)

    logger.info("Bot started")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    main() 