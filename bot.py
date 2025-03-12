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

# YouTube request settings
# Ruota tra diversi user agent per evitare il rilevamento
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0'
]

# Percorso del file dei cookie (se esiste)
COOKIE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')
HAS_COOKIE_FILE = os.path.isfile(COOKIE_FILE)

if HAS_COOKIE_FILE:
    logger.info(f"Cookie file trovato: {COOKIE_FILE}")
else:
    logger.warning(f"Cookie file non trovato in: {COOKIE_FILE}")
    logger.warning("Per migliorare l'affidabilità, crea un file cookies.txt con i cookie di YouTube")

if not TELEGRAM_TOKEN:
    raise ValueError("Please set the TELEGRAM_TOKEN environment variable")

if not OPENAI_API_KEY:
    logger.warning("OpenAI API key not found. Transcription and summarization with OpenAI will not work.")

def retry_on_error(max_retries=3, initial_delay=2):
    """
    Decoratore per riprovare le funzioni in caso di errore con backoff esponenziale.
    Utile per gestire problemi temporanei come rate limiting.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            retries = 0
            delay = initial_delay
            
            while retries < max_retries:
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    retries += 1
                    if retries >= max_retries:
                        logger.error(f"Errore persistente dopo {max_retries} tentativi: {e}")
                        raise e
                    
                    logger.warning(f"Errore: {e}. Ritentativo {retries}/{max_retries} tra {delay} secondi...")
                    await asyncio.sleep(delay)
                    # Backoff esponenziale con jitter per evitare richieste sincronizzate
                    delay = delay * 2 + random.uniform(0, 1)
            
        return wrapper
    return decorator

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
    """
    Get the title of a YouTube video using yt-dlp con configurazioni anti-bot.
    Usa user-agent random e cookie file se disponibile.
    """
    # Rotazione degli user agent per sembrare più "umani"
    selected_user_agent = random.choice(USER_AGENTS)
    
    # Define YT-DLP options with anti-bot measures
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'user_agent': selected_user_agent,
        'referer': 'https://www.youtube.com/',
        # Opzioni aggiuntive per evitare restrizioni
        'nocheckcertificate': True,
        'ignoreerrors': True,
        # Inserisci un delay casuale per simulare comportamento umano
        'sleep_interval': random.uniform(1, 3),
        'max_sleep_interval': 5,
    }
    
    # Aggiungi cookie file se esiste
    if HAS_COOKIE_FILE:
        ydl_opts['cookiefile'] = COOKIE_FILE
    
    # Try to get video info
    try:
        logger.info(f"Recupero titolo per video ID: {video_id} con User-Agent: {selected_user_agent[:30]}...")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            title = info.get('title', f"Video {video_id}")
            logger.info(f"Titolo recuperato con successo: {title[:30]}...")
            return title
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
    """
    Download audio from a YouTube video with enhanced anti-bot measures.
    Usa user-agent diversi, cookie file, e tecniche avanzate di evasione del rilevamento.
    """
    try:
        logger.info(f"Downloading audio for video ID: {video_id}")
        # Create a temporary file
        temp_dir = tempfile.gettempdir()
        output_file = os.path.join(temp_dir, f"{video_id}.mp3")
        
        # Rotazione degli user agent per sembrare più "umani"
        selected_user_agent = random.choice(USER_AGENTS)
        
        # Header HTTP aggiuntivi per simulare un browser web reale
        http_headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'cross-site',
            'Pragma': 'no-cache',
            'Cache-Control': 'no-cache',
        }
        
        # Define YT-DLP options with enhanced anti-bot configurations
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
            'user_agent': selected_user_agent,
            'referer': 'https://www.google.com/',  # Simula una provenienza da ricerca Google
            # Opzioni aggiuntive per evitare restrizioni
            'nocheckcertificate': True,
            'ignoreerrors': True,
            # Inserisci un delay casuale per simulare comportamento umano
            'sleep_interval': random.uniform(2, 5),
            'max_sleep_interval': 10,
            # Header HTTP personalizzati
            'http_headers': http_headers,
            # Evita le restrizioni di geo-blocking
            'geo_bypass': True,
            # Non usare IPv6 (alcuni filtri si basano su IPv6)
            'source_address': '0.0.0.0',
            # Ulteriori opzioni avanzate
            'extractor_retries': 5,
            'fragment_retries': 5,
            'skip_unavailable_fragments': True,
            'keepvideo': False,
        }
        
        # Aggiungi cookie file se esiste
        if HAS_COOKIE_FILE:
            ydl_opts['cookiefile'] = COOKIE_FILE
            logger.info("Utilizzando il file cookies.txt")
        else:
            logger.warning("File cookies.txt non trovato. L'utilizzo di cookie aumenterebbe le probabilità di successo.")
        
        # Download the audio with multiple attempts if needed
        retries = 3
        delay = 3  # in secondi
        
        for attempt in range(retries):
            try:
                # Cambia leggermente l'URL ad ogni tentativo per evitare pattern detection
                url_suffix = "" if attempt == 0 else f"&t={random.randint(0, 10)}"
                video_url = f"https://www.youtube.com/watch?v={video_id}{url_suffix}"
                
                logger.info(f"Tentativo {attempt+1}/{retries} download audio con User-Agent: {selected_user_agent[:30]}...")
                # Aggiungi un delay casuale prima del download per simulare comportamento umano
                await asyncio.sleep(random.uniform(1, 3))
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([video_url])
                
                # Verifica che il file esista e abbia dimensione > 0
                if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                    logger.info(f"Audio downloaded to: {output_file}")
                    return output_file
                else:
                    raise Exception("File di output non creato o vuoto")
            
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"Errore tentativo {attempt+1}: {error_msg}")
                
                # Se l'errore è 403 Forbidden, potrebbero essere necessarie ulteriori misure
                if "403" in error_msg or "Forbidden" in error_msg:
                    logger.warning("Rilevato errore 403 Forbidden - YouTube sta bloccando il download")
                    
                    # Prova a modificare strategia
                    if attempt < retries - 1:
                        # Cambia drasticamente la strategia ad ogni tentativo
                        if attempt == 0:
                            # Secondo tentativo: prova con un formato diverso
                            ydl_opts['format'] = 'worstaudio'  # Prova con audio a bassa qualità
                            logger.info("Cambio strategia: provo con audio a bassa qualità")
                        elif attempt == 1:
                            # Terzo tentativo: prova con un approccio diverso (senza postprocessing)
                            ydl_opts['format'] = 'bestaudio'
                            ydl_opts.pop('postprocessors', None)  # Rimuovi post-processing
                            ydl_opts['extract_flat'] = True
                            logger.info("Cambio strategia: provo senza post-processing")
                
                if attempt < retries - 1:
                    wait_time = delay * (2 ** attempt) + random.uniform(1, 3)  # backoff esponenziale con jitter
                    logger.warning(f"Riprovo tra {wait_time:.1f} secondi...")
                    await asyncio.sleep(wait_time)
                    # Cambia user agent ad ogni tentativo
                    selected_user_agent = random.choice(USER_AGENTS)
                    ydl_opts['user_agent'] = selected_user_agent
                    # Cambia anche altri parametri per evitare detection
                    http_headers['Accept-Language'] = random.choice(['en-US,en;q=0.9', 'en-GB,en;q=0.8', 'en;q=0.7'])
                    ydl_opts['http_headers'] = http_headers
                else:
                    logger.error(f"Failed to download audio after {retries} attempts: {error_msg}")
                    if "HTTP Error 403: Forbidden" in error_msg:
                        logger.error("YouTube ha bloccato sistematicamente il download. "
                                    "È possibile che siano necessari nuovi cookie o un proxy.")
                    return None
        
        return None
    
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

async def get_transcript(video_id: str, context: Optional[ContextTypes.DEFAULT_TYPE] = None, query = None) -> Optional[str]:
    """Get transcript using existing YouLearn functionality with retry logic."""
    # Try to get transcript from YouTube with retry logic
    for attempt in range(3):
        try:
            transcript = await get_transcript_from_youtube(video_id)
            if transcript:
                return transcript
            break  # Se otteniamo una risposta valida (anche se null), usciamo dal ciclo
        except Exception as e:
            logger.warning(f"Errore tentativo {attempt+1}/3 recupero trascrizione: {e}")
            if attempt < 2:  # Non aspettiamo dopo l'ultimo tentativo
                await asyncio.sleep(2 * (2 ** attempt))  # Backoff esponenziale
    
    # Se non è disponibile la trascrizione da YouTube e abbiamo un contesto di conversazione
    # chiediamo all'utente se vuole utilizzare Whisper (che consumerà più crediti API)
    if context and query:
        keyboard = [
            [
                InlineKeyboardButton("✅ Sì, usa Whisper", callback_data=f"whisper_{video_id}"),
                InlineKeyboardButton("❌ No, annulla", callback_data="cancel"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "❓ Non è stato possibile ottenere la trascrizione direttamente da YouTube.\n\n"
            "Vuoi utilizzare OpenAI Whisper per trascrivere l'audio?\n"
            "Nota: questo utilizzerà crediti API aggiuntivi.",
            reply_markup=reply_markup
        )
        return None
    
    # Nel caso il contesto non sia disponibile o per uso interno
    # tentativo diretto con Whisper (comportamento originale)
    audio_file = await download_audio(video_id)
    if audio_file:
        transcript = await transcribe_with_whisper_api(audio_file)
        return transcript
    
    return None

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button presses."""
    query = update.callback_query
    await query.answer()  # Acknowledge the button press
    
    # Controlla se è una richiesta di trascrizione con Whisper
    if query.data.startswith("whisper_"):
        video_id = query.data.split("_")[1]
        context.user_data['video_id'] = video_id  # Salva l'ID per riferimento futuro
        await query.edit_message_text("⏳ Trascrizione con Whisper in corso (potrebbe richiedere tempo)...")
        
        # Scarica l'audio e trascrivilo
        audio_file = await download_audio(video_id)
        if audio_file:
            transcript = await transcribe_with_whisper_api(audio_file)
            if transcript:
                video_title = get_video_title(video_id)
                # Invia la trascrizione
                chunks = [transcript[i:i+4000] for i in range(0, len(transcript), 4000)]
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        header = f"📝 Trascrizione (Whisper): {video_title}\n\n"
                        await query.message.reply_text(header + chunk)
                    else:
                        await query.message.reply_text(chunk)
                await query.edit_message_text("✅ Trascrizione completata!")
                return
        
        await query.edit_message_text("❌ Non è stato possibile trascrivere l'audio con Whisper.")
        return
    
    # Gestisce il caso di annullamento
    if query.data == "cancel":
        await query.edit_message_text("⚠️ Operazione annullata.")
        return
    
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
        transcript = await get_transcript(video_id, context, query)
        if transcript is None:
            # La funzione get_transcript ha mostrato la richiesta per Whisper se necessario
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