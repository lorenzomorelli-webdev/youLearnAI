#!/usr/bin/env python3
"""
YouLearn Telegram Bot - YouTube Video Transcription and Summarization Bot
Integrates the YouLearn functionality with a Telegram bot interface.
"""

import os
import logging
from pathlib import Path
from typing import Optional, Literal, Dict, Any
import re
import httpx

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import yt_dlp
import requests
import dotenv
from openai import OpenAI
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

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

# Proxy configuration - SOLO per YouTube
USE_YOUTUBE_PROXY = os.getenv("USE_PROXY", "false").lower() == "true"
PROXY_URL = os.getenv("PROXY_URL")  # Format: "http://username:password@host:port"

# Whitelist configuration
ALLOWED_USERS = os.getenv("ALLOWED_USERS", "")

def get_youtube_proxy_dict() -> Optional[Dict[str, str]]:
    """Restituisce un dizionario di configurazione proxy per YouTube se abilitato."""
    if PROXY_URL:
        return {
            "http": PROXY_URL,
            "https": PROXY_URL
        }
    return None

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
    
    # Usa il proxy solo per YouTube
    if USE_YOUTUBE_PROXY and PROXY_URL:
        ydl_opts['proxy'] = PROXY_URL
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            return info.get('title', f"Video {video_id}")
    except Exception as e:
        logger.error(f"Error getting video title: {e}")
        return f"Video {video_id}"

def get_transcript_from_youtube(video_id: str) -> Optional[str]:
    """Get video transcript directly from YouTube."""
    try:
        # Usa il proxy solo per YouTube
        proxies = get_youtube_proxy_dict()
        
        # Try first with specific languages
        try:
            transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en', 'it'], proxies=proxies)
            return ' '.join([entry['text'] for entry in transcript])
        except (NoTranscriptFound, TranscriptsDisabled):
            # Try with automatic language detection
            transcript = YouTubeTranscriptApi.get_transcript(video_id, proxies=proxies)
            return ' '.join([entry['text'] for entry in transcript])
            
    except Exception as e:
        logger.error(f"Error retrieving transcript: {e}")
        return None

def summarize_with_ai(transcript: str, video_title: str, service: Literal["openai", "deepseek"] = "openai") -> Optional[str]:
    """Generate a summary using AI services."""
    try:
        system_prompt = "You are an expert at summarizing video content in Italian. Create a comprehensive summary of the following video transcript."
        user_prompt = f"Title: {video_title}\n\nTranscript:\n{transcript}\n\nPlease provide a detailed summary of this video's content, highlighting the main points, key insights, and important details."
        
        # Set up OpenAI client WITHOUT proxy configuration (connessione diretta)
        client_kwargs: Dict[str, Any] = {}
        
        # Add API key based on service
        if service == "openai":
            if not OPENAI_API_KEY:
                return None
            client_kwargs["api_key"] = OPENAI_API_KEY
            model = "gpt-4o-mini"
            
        elif service == "deepseek":
            if not DEEPSEEK_API_KEY:
                return None
            client_kwargs["api_key"] = DEEPSEEK_API_KEY
            client_kwargs["base_url"] = "https://api.deepseek.com"
            model = "deepseek-chat"
        
        # Create OpenAI client WITHOUT proxy
        client = OpenAI(**client_kwargs)
        
        # Generate summary
        response = client.chat.completions.create(
            model=model,
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
        await query.edit_message_text("⏳ Elaborazione in corso...")
        await process_request(query, context, video_id)
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
        transcript = get_transcript_from_youtube(video_id)
        
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
            summary = summarize_with_ai(transcript, video_title, service)
            
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
        await update.effective_message.reply_text(
            "❌ Si è verificato un errore durante l'elaborazione della richiesta.\n"
            "Per favore, riprova più tardi."
        )

def main() -> None:
    """Start the bot."""
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN non impostato. Impossibile avviare il bot.")
        return
        
    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_youtube_url))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_error_handler(error_handler)

    # Informazioni di avvio
    proxy_status = "abilitato solo per YouTube" if USE_YOUTUBE_PROXY and PROXY_URL else "disabilitato"
    logger.info(f"YouLearn Bot avviato. Proxy {proxy_status}.")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    main() 