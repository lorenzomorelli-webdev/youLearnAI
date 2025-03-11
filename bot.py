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

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import yt_dlp
import re
import requests
from tqdm import tqdm
import dotenv
from openai import OpenAI

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

if not TELEGRAM_TOKEN:
    raise ValueError("Please set the TELEGRAM_TOKEN environment variable")

if not OPENAI_API_KEY:
    logger.warning("OpenAI API key not found. Transcription and summarization with OpenAI will not work.")

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
    """Get the title of a YouTube video."""
    # Define YT-DLP options
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
    }
    
    # Try to get video info
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            return info.get('title', f"Video {video_id}")
    except Exception as e:
        logger.error(f"Error getting video title: {e}")
        return f"Video {video_id}"

async def get_transcript_from_youtube(video_id: str) -> Optional[str]:
    """Try to get transcript directly from YouTube."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
        
        logger.info(f"Getting transcript for video ID: {video_id}")
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['en', 'it'])
        
        # Combine all transcript pieces into a single text
        transcript = ' '.join([item['text'] for item in transcript_list])
        logger.info("Successfully retrieved transcript from YouTube")
        return transcript
    
    except (TranscriptsDisabled, NoTranscriptFound) as e:
        logger.warning(f"No transcript available on YouTube: {e}")
        return None
    except Exception as e:
        logger.error(f"Error retrieving transcript from YouTube: {e}")
        return None

async def download_audio(video_id: str) -> Optional[str]:
    """Download audio from a YouTube video."""
    try:
        logger.info(f"Downloading audio for video ID: {video_id}")
        # Create a temporary file
        temp_dir = tempfile.gettempdir()
        output_file = os.path.join(temp_dir, f"{video_id}.mp3")
        
        # Define YT-DLP options
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_file,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',
            }],
            'quiet': True,
            'no_warnings': True,
        }
        
        # Download the audio
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        
        logger.info(f"Audio downloaded to: {output_file}")
        return output_file
    
    except Exception as e:
        logger.error(f"Error downloading audio: {e}")
        return None

async def transcribe_with_whisper_api(audio_file: str) -> Optional[str]:
    """Transcribe audio using OpenAI's Whisper API."""
    if not OPENAI_API_KEY:
        logger.error("Cannot use Whisper API without OpenAI API key")
        return None
    
    try:
        logger.info(f"Transcribing audio file with OpenAI Whisper API: {audio_file}")
        
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        with open(audio_file, "rb") as audio:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio,
                language="it"  # Usa italiano per default, puoi anche rilevare automaticamente
            )
        
        transcript = response.text
        logger.info("Audio transcription completed via API")
        
        # Clean up the temporary file
        try:
            os.remove(audio_file)
            logger.info(f"Temporary file removed: {audio_file}")
        except Exception as e:
            logger.warning(f"Could not remove temporary file {audio_file}: {e}")
        
        return transcript
    
    except Exception as e:
        logger.error(f"Error transcribing audio with OpenAI API: {e}")
        return None

async def summarize_with_ai(transcript: str, video_title: str, service: Literal["openai", "deepseek"] = "openai") -> Optional[str]:
    """Generate a summary of the transcript using either OpenAI's GPT or Deepseek."""
    
    # Prepare the prompt
    system_prompt = "You are an expert at summarizing video content. Create a comprehensive summary of the following video transcript."
    user_prompt = f"Title: {video_title}\n\nTranscript:\n{transcript}\n\nPlease provide a detailed summary of this video's content, highlighting the main points, key insights, and important details."
    
    try:
        logger.info(f"Generating summary with {service.upper()}")
        
        if service == "openai":
            if not OPENAI_API_KEY:
                logger.error("OpenAI API key not found. Set the OPENAI_API_KEY environment variable.")
                return None
                
            client = OpenAI(api_key=OPENAI_API_KEY)
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",  # Use a smaller model to save costs
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=1500,
                temperature=0.5,
            )
            
        elif service == "deepseek":
            if not DEEPSEEK_API_KEY:
                logger.error("Deepseek API key not found. Set the DEEPSEEK_API_KEY environment variable.")
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
            
        summary = response.choices[0].message.content
        logger.info("Summary generation complete")
        return summary
        
    except Exception as e:
        logger.error(f"Error generating summary with {service}: {e}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
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
    url = update.message.text
    video_id = extract_video_id(url)
    
    if not video_id:
        await update.message.reply_text(
            "❌ Link non valido. Per favore, invia un link YouTube valido."
        )
        return
    
    # Store video_id in user_data for later use
    context.user_data['video_id'] = video_id
    context.user_data['video_url'] = url
    
    # Create inline keyboard
    keyboard = [
        [
            InlineKeyboardButton("📝 Trascrizione", callback_data='transcript'),
            InlineKeyboardButton("📚 Riassunto", callback_data='summary')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎥 Cosa vuoi fare con questo video?",
        reply_markup=reply_markup
    )

async def get_transcript(video_id: str) -> Optional[str]:
    """Get transcript using existing YouLearn functionality."""
    # Try to get transcript from YouTube
    transcript = await get_transcript_from_youtube(video_id)
    
    # If no transcript available, try Whisper API
    if not transcript:
        audio_file = await download_audio(video_id)
        if audio_file:
            transcript = await transcribe_with_whisper_api(audio_file)
    
    return transcript

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button presses."""
    query = update.callback_query
    await query.answer()  # Acknowledge the button press
    
    video_id = context.user_data.get('video_id')
    if not video_id:
        await query.edit_message_text("❌ Sessione scaduta. Invia nuovamente il link YouTube.")
        return
    
    # Show processing message
    await query.edit_message_text("⏳ Elaborazione in corso...")
    
    try:
        # Get video title
        video_title = get_video_title(video_id)
        
        # Get transcript
        transcript = await get_transcript(video_id)
        if not transcript:
            await query.edit_message_text("❌ Non è stato possibile ottenere la trascrizione del video.")
            return
        
        if query.data == 'transcript':
            # Send transcript in chunks due to Telegram message length limits
            chunks = [transcript[i:i+4000] for i in range(0, len(transcript), 4000)]
            for i, chunk in enumerate(chunks):
                if i == 0:
                    header = f"📝 Trascrizione: {video_title}\n\n"
                    await query.message.reply_text(header + chunk)
                else:
                    await query.message.reply_text(chunk)
            
            # Update status message
            await query.edit_message_text("✅ Trascrizione completata!")
                    
        elif query.data == 'summary':
            await query.edit_message_text("⏳ Generazione riassunto in corso...")
            
            # Choose the AI service (defaulting to OpenAI if both are available)
            ai_service = "openai" if OPENAI_API_KEY else "deepseek"
            
            summary = await summarize_with_ai(transcript, video_title, ai_service)
            if summary:
                response = f"📚 Riassunto: {video_title}\n\n{summary}"
                # Split long summaries if needed
                if len(response) > 4000:
                    chunks = [response[i:i+4000] for i in range(0, len(response), 4000)]
                    for i, chunk in enumerate(chunks):
                        await query.message.reply_text(chunk)
                else:
                    await query.message.reply_text(response)
                
                # Update status message
                await query.edit_message_text("✅ Riassunto completato!")
            else:
                await query.edit_message_text("❌ Non è stato possibile generare il riassunto.")
                
    except Exception as e:
        logger.error(f"Error processing request: {e}")
        await query.edit_message_text(
            "❌ Si è verificato un errore durante l'elaborazione della richiesta."
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log Errors caused by Updates."""
    logger.error(f"Update {update} caused error {context.error}")
    if update.effective_message:
        await update.effective_message.reply_text(
            "❌ Si è verificato un errore. Per favore, riprova più tardi."
        )

def main() -> None:
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_youtube_url))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Add error handler
    application.add_error_handler(error_handler)

    # Log startup
    logger.info("Starting bot in polling mode")
    
    # Start the Bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main() 