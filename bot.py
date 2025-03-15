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

# SmartProxy configuration
USE_PROXY = os.getenv("USE_PROXY", "false").lower() == "true"
PROXY_USERNAME = os.getenv("PROXY_USERNAME")
PROXY_PASSWORD = os.getenv("PROXY_PASSWORD")
PROXY_HOST = os.getenv("PROXY_HOST", "gate.smartproxy.com")
PROXY_PORT = os.getenv("PROXY_PORT", "10001")

# Configura il proxy solo se tutte le variabili necessarie sono presenti
if USE_PROXY and PROXY_USERNAME and PROXY_PASSWORD:
    PROXY_URL = f"http://{PROXY_USERNAME}:{PROXY_PASSWORD}@{PROXY_HOST}:{PROXY_PORT}"
    PROXIES = {
        'http': PROXY_URL,
        'https': PROXY_URL
    }
    logger.info(f"Proxy configurato: {PROXY_HOST}:{PROXY_PORT}")
    logger.info(f"Ambiente Heroku: {IS_HEROKU}")
    logger.info("Credenziali proxy presenti e configurate correttamente")
else:
    PROXIES = None
    if USE_PROXY:
        logger.warning("Proxy richiesto ma credenziali mancanti. Verifica le variabili d'ambiente:")
        logger.warning(f"USE_PROXY: {USE_PROXY}")
        logger.warning(f"PROXY_USERNAME presente: {bool(PROXY_USERNAME)}")
        logger.warning(f"PROXY_PASSWORD presente: {bool(PROXY_PASSWORD)}")
        logger.warning(f"PROXY_HOST: {PROXY_HOST}")
        logger.warning(f"PROXY_PORT: {PROXY_PORT}")
    else:
        logger.info("Proxy non configurato. Utilizzo connessione diretta.")

# YouTube request settings
# Ruota tra diversi user agent per evitare il rilevamento
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0'
]

# Rileva se l'app è in esecuzione su Heroku
IS_HEROKU = "DYNO" in os.environ

# Log delle informazioni di ambiente per il debug
logger.info(f"Ambiente di esecuzione: {'Heroku' if IS_HEROKU else 'Locale/Altro'}")
logger.info(f"Sistema: {platform.system()} {platform.release()}")
logger.info(f"Python: {sys.version}")
logger.info(f"Directory corrente: {os.getcwd()}")
logger.info(f"Contenuto directory: {os.listdir('.')}")
logger.info(f"Proxy attivo: {USE_PROXY}")
logger.info(f"Ambiente Heroku: {IS_HEROKU}")

if not TELEGRAM_TOKEN:
    raise ValueError("Please set the TELEGRAM_TOKEN environment variable")

if not OPENAI_API_KEY:
    logger.warning("OpenAI API key not found. Transcription and summarization with OpenAI will not work.")

# Funzione per creare una sessione requests con proxy per YouTube
def get_youtube_session():
    """
    Crea una sessione requests configurata per YouTube con proxy se disponibile.
    Questo permette di utilizzare il proxy solo per le chiamate a YouTube.
    """
    session = requests.Session()
    
    # Imposta un User-Agent casuale
    selected_user_agent = random.choice(USER_AGENTS)
    session.headers.update({'User-Agent': selected_user_agent})
    
    # Aggiungi il proxy solo se configurato
    if PROXIES:
        session.proxies.update(PROXIES)
        logger.info(f"Sessione YouTube creata con proxy: {PROXY_HOST}")
        logger.info(f"User-Agent utilizzato: {selected_user_agent}")
        if IS_HEROKU:
            logger.info("Esecuzione su Heroku - Verificando configurazione proxy...")
            try:
                # Test della connessione proxy
                test_response = session.get('https://api.ipify.org?format=json')
                logger.info(f"Test connessione proxy - IP utilizzato: {test_response.json().get('ip')}")
                logger.info(f"Test connessione proxy - Status code: {test_response.status_code}")
            except Exception as e:
                logger.error(f"Errore nel test del proxy su Heroku: {e}")
    else:
        logger.info(f"Sessione YouTube creata senza proxy. User-Agent: {selected_user_agent}")
    
    return session

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
    Usa user-agent random e proxy se disponibile.
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
    
    # Aggiungi proxy se configurato
    if PROXIES:
        ydl_opts['proxy'] = PROXIES['https']
        logger.info("Utilizzo proxy per il recupero del titolo del video")
    
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

# Classe personalizzata per utilizzare il proxy con YouTubeTranscriptApi
class ProxyTranscriptApi:
    """
    Wrapper per YouTubeTranscriptApi che utilizza il proxy configurato.
    Questo permette di utilizzare il proxy solo per le chiamate a YouTube.
    """
    @staticmethod
    def get_transcript(video_id, languages=None):
        """
        Ottiene la trascrizione di un video YouTube utilizzando il proxy se configurato.
        """
        if PROXIES:
            # Configura temporaneamente il proxy per la richiesta
            import http.client
            import urllib.request
            
            # Salva le impostazioni originali
            original_http_connection = http.client.HTTPConnection
            original_https_connection = http.client.HTTPSConnection
            original_opener = urllib.request._opener
            
            try:
                # Configura il proxy
                proxy_handler = urllib.request.ProxyHandler(PROXIES)
                opener = urllib.request.build_opener(proxy_handler)
                urllib.request.install_opener(opener)
                
                # Esegui la richiesta
                logger.info(f"Richiesta trascrizione con proxy per video ID: {video_id}")
                return YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
            finally:
                # Ripristina le impostazioni originali
                urllib.request._opener = original_opener
                http.client.HTTPConnection = original_http_connection
                http.client.HTTPSConnection = original_https_connection
        else:
            # Usa la chiamata standard senza proxy
            return YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
    
    @staticmethod
    def list_transcripts(video_id):
        """
        Elenca le trascrizioni disponibili per un video YouTube utilizzando il proxy se configurato.
        """
        if PROXIES:
            # Configura temporaneamente il proxy per la richiesta
            import http.client
            import urllib.request
            
            # Salva le impostazioni originali
            original_http_connection = http.client.HTTPConnection
            original_https_connection = http.client.HTTPSConnection
            original_opener = urllib.request._opener
            
            try:
                # Configura il proxy
                proxy_handler = urllib.request.ProxyHandler(PROXIES)
                opener = urllib.request.build_opener(proxy_handler)
                urllib.request.install_opener(opener)
                
                # Esegui la richiesta
                logger.info(f"Richiesta lista trascrizioni con proxy per video ID: {video_id}")
                return YouTubeTranscriptApi.list_transcripts(video_id)
            finally:
                # Ripristina le impostazioni originali
                urllib.request._opener = original_opener
                http.client.HTTPConnection = original_http_connection
                http.client.HTTPSConnection = original_https_connection
        else:
            # Usa la chiamata standard senza proxy
            return YouTubeTranscriptApi.list_transcripts(video_id)

async def get_transcript_from_youtube(video_id: str) -> Optional[str]:
    """
    Prova a ottenere la trascrizione direttamente da YouTube.
    Usa diverse strategie e gestisce le particolarità di Heroku.
    Utilizza il proxy se configurato.
    """
    try:
        logger.info(f"Richiesta trascrizione per video ID: {video_id}")
        logger.info(f"Ambiente: {'Heroku' if IS_HEROKU else 'Non-Heroku'}")
        logger.info(f"Proxy configurato: {bool(PROXIES)}")
        
        # Strategia 1: Prova con lista di lingue specifiche
        try:
            logger.info("Tentativo trascrizione con lingue specifiche (en, it)")
            transcript_list = ProxyTranscriptApi.get_transcript(video_id, languages=['en', 'it'])
            transcript = ' '.join([item['text'] for item in transcript_list])
            logger.info("Trascrizione ottenuta con successo (lingua specificata)")
            return transcript
        except (NoTranscriptFound, TranscriptsDisabled) as e:
            logger.warning(f"Nessuna trascrizione in lingue specifiche: {e}")
            
            # Strategia 2: Prova con rilevamento automatico della lingua
            try:
                logger.info("Tentativo trascrizione con rilevamento automatico lingua")
                transcript_list = ProxyTranscriptApi.get_transcript(video_id)
                transcript = ' '.join([item['text'] for item in transcript_list])
                logger.info("Trascrizione ottenuta con rilevamento automatico lingua")
                return transcript
            except Exception as e2:
                logger.warning(f"Rilevamento automatico lingua fallito: {e2}")
                
                # Strategia 3: Prova a elencare tutte le trascrizioni disponibili e seleziona la prima
                try:
                    transcript_list = ProxyTranscriptApi.list_transcripts(video_id)
                    
                    # Prendi la prima trascrizione disponibile
                    for transcript_obj in transcript_list:
                        transcript_data = transcript_obj.fetch()
                        transcript = ' '.join([item['text'] for item in transcript_data])
                        logger.info(f"Successfully retrieved transcript in {transcript_obj.language_code}")
                        return transcript
                        
                except Exception as e3:
                    logger.warning(f"Failed to list available transcripts: {e3}")
                    # Continua con le eccezioni esterne
                    raise e3
    
    except (TranscriptsDisabled, NoTranscriptFound) as e:
        logger.warning(f"No transcript available on YouTube: {e}")
        logger.warning(f"Video URL: https://www.youtube.com/watch?v={video_id}")
        return None
    except Exception as e:
        logger.error(f"Error retrieving transcript from YouTube: {e}")
        logger.error(f"Video URL: https://www.youtube.com/watch?v={video_id}")
        # Log dettagliati per il debug
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return None

async def download_audio(video_id: str) -> Optional[str]:
    """
    Download audio from a YouTube video with enhanced anti-bot measures.
    Usa user-agent diversi, proxy e tecniche avanzate di evasione del rilevamento.
    Adattato per funzionare su Heroku.
    """
    try:
        logger.info(f"Avvio download audio per video ID: {video_id}")
        logger.info(f"Ambiente: {'Heroku' if IS_HEROKU else 'Non-Heroku'}")
        logger.info(f"Proxy attivo: {bool(PROXIES)}")
        
        # Create a temporary file
        temp_dir = tempfile.gettempdir()
        output_file = os.path.join(temp_dir, f"{video_id}.mp3")
        
        # Mostra informazioni sul percorso del file temporaneo
        logger.info(f"Directory temporanea: {temp_dir}")
        logger.info(f"Percorso file output: {output_file}")
        logger.info(f"Directory temp esiste: {os.path.exists(temp_dir)}")
        logger.info(f"Directory temp scrivibile: {os.access(temp_dir, os.W_OK)}")
        
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
            # Forza IPv4 (può aiutare ad evitare blocchi)
            'force_ipv4': True,
            # Limita la velocità di download per sembrare meno sospetto
            'ratelimit': 1000000,  # 1 MB/s
        }
        
        # Aggiungi proxy se configurato
        if PROXIES:
            ydl_opts['proxy'] = PROXIES['https']
            logger.info("Utilizzo proxy per il download dell'audio")
        
        # Se siamo su Heroku, aggiungi altre opzioni specifiche
        if IS_HEROKU:
            # Su Heroku, prova con opzioni che hanno più probabilità di successo
            # Prova con un formato legacy (come il formato 18 o 140) che ha meno probabilità di essere bloccato
            ydl_opts['format'] = '140/bestaudio[acodec^=mp4a]/18/best'  # Formato Audio-Only MP4 (M4A)
            # Evita il post-processing che potrebbe fallire e passa direttamente il file audio
            if 'postprocessors' in ydl_opts:
                ydl_opts.pop('postprocessors', None)
            
            # Aumenta il timeout per le richieste HTTP su Heroku
            ydl_opts['socket_timeout'] = 30
            # Limita ulteriormente la velocità di download su Heroku
            ydl_opts['ratelimit'] = 500000  # 500 KB/s
            logger.info("Configurazione ottimizzata per Heroku")
            
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
                            ydl_opts['format'] = '18/best'  # Prova con il formato video legacy
                            # Prova a forzare IPv6 se IPv4 ha fallito
                            ydl_opts['force_ipv4'] = False
                            ydl_opts['force_ipv6'] = True
                            logger.info("Cambio strategia: provo con formato legacy e IPv6")
                        elif attempt == 1:
                            # Terzo tentativo: prova con un approccio completamente diverso
                            ydl_opts['format'] = 'worstaudio'
                            ydl_opts.pop('postprocessors', None)  # Rimuovi post-processing
                            ydl_opts['force_ipv4'] = True  # Torna a IPv4
                            ydl_opts['force_ipv6'] = False
                            # Imposta client web diverso
                            ydl_opts['extractor_args'] = {'youtube': {'player_client': ['web', 'tv']}}
                            logger.info("Cambio strategia: provo con audio a bassa qualità e client diverso")
                
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
        # Log dettagliati per il debug
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
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
                model="gpt-4o-mini",  # Utilizziamo gpt-4o-mini come richiesto
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=1500,
                temperature=0.5,
            )
            logger.info("Utilizzato modello gpt-4o-mini per il riassunto")
            
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
            logger.info("Utilizzato modello deepseek-chat per il riassunto")
            
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

async def check_transcript_availability(video_id: str) -> bool:
    """
    Verifica rapidamente se sono disponibili trascrizioni per un video.
    Questo è utile per decidere se tentare il download dell'audio o no.
    Utilizza il proxy se configurato.
    """
    try:
        logger.info(f"Checking transcript availability for video ID: {video_id}")
        
        try:
            # Non scarichiamo effettivamente la trascrizione, controlliamo solo se è disponibile
            transcript_list = ProxyTranscriptApi.list_transcripts(video_id)
            # Se arriviamo qui, ci sono trascrizioni disponibili
            available_languages = [t.language_code for t in transcript_list]
            logger.info(f"Transcripts available in languages: {available_languages}")
            return True
        except (TranscriptsDisabled, NoTranscriptFound):
            logger.warning(f"No transcripts available for video ID: {video_id}")
            return False
        except Exception as e:
            logger.error(f"Error checking transcript availability: {e}")
            return False
    
    except Exception as e:
        logger.error(f"Error importing or using YouTubeTranscriptApi: {e}")
        return False

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
    
    # Verifica rapidamente se il video ha trascrizioni disponibili
    has_transcript = await check_transcript_availability(video_id)
    context.user_data['has_transcript'] = has_transcript
    
    # Create inline keyboard with more options
    keyboard = [
        [
            InlineKeyboardButton("📝 Trascrizione", callback_data='transcript')
        ],
        [
            InlineKeyboardButton("📚 Riassunto OpenAI", callback_data='summary_openai'),
            InlineKeyboardButton("📚 Riassunto Deepseek", callback_data='summary_deepseek')
        ]
    ]
    
    # Se non ci sono trascrizioni disponibili, avvisa l'utente
    reply_text = "🎥 Cosa vuoi fare con questo video?"
    if not has_transcript and IS_HEROKU:
        reply_text = "⚠️ Questo video non ha trascrizioni disponibili e su Heroku potrebbe non essere possibile scaricare l'audio.\n" + reply_text
    elif not has_transcript:
        reply_text = "⚠️ Questo video non ha trascrizioni disponibili. Si tenterà di scaricare l'audio e trascriverlo con Whisper.\n" + reply_text
    
    # Aggiungi informazioni sui modelli disponibili
    available_models = []
    if OPENAI_API_KEY:
        available_models.append("OpenAI (gpt-4o-mini)")
    if DEEPSEEK_API_KEY:
        available_models.append("Deepseek")
    
    if available_models:
        reply_text += f"\n\nModelli disponibili per il riassunto: {', '.join(available_models)}"
    else:
        reply_text += "\n\n⚠️ Nessun modello AI configurato per il riassunto. Contatta l'amministratore del bot."
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        reply_text,
        reply_markup=reply_markup
    )

async def get_transcript(video_id: str, context: Optional[ContextTypes.DEFAULT_TYPE] = None, query = None) -> Optional[str]:
    """Get transcript using existing YouLearn functionality with retry logic."""
    # Se il contesto è disponibile, verifica se abbiamo già controllato la disponibilità della trascrizione
    has_transcript = context.user_data.get('has_transcript') if context else None
    
    # Se sappiamo già che non ci sono trascrizioni e siamo su Heroku, avvisa subito l'utente
    if has_transcript is False and IS_HEROKU and context and query:
        keyboard = [
            [
                InlineKeyboardButton("✅ Sì, usa Whisper", callback_data=f"whisper_{video_id}"),
                InlineKeyboardButton("❌ No, annulla", callback_data="cancel"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "❓ Questo video non ha trascrizioni disponibili su YouTube e siamo su Heroku, dove il download potrebbe fallire.\n\n"
            "Vuoi comunque provare a utilizzare OpenAI Whisper per trascrivere l'audio?\n"
            "Nota: questo utilizzerà crediti API aggiuntivi e potrebbe non funzionare.",
            reply_markup=reply_markup
        )
        return None
    
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
        
        message = "❓ Non è stato possibile ottenere la trascrizione direttamente da YouTube.\n\n"
        if IS_HEROKU:
            message += "⚠️ Nota: su Heroku, il download dell'audio potrebbe fallire a causa delle restrizioni di YouTube.\n\n"
        
        message += "Vuoi utilizzare OpenAI Whisper per trascrivere l'audio?\n" 
        message += "Nota: questo utilizzerà crediti API aggiuntivi."
        
        await query.edit_message_text(message, reply_markup=reply_markup)
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
        
        # Se siamo su Heroku, avvisiamo preventivamente l'utente delle possibili difficoltà
        if IS_HEROKU:
            await query.edit_message_text(
                "⏳ Tentativo di trascrizione con Whisper in corso...\n\n"
                "⚠️ Nota: su Heroku, YouTube spesso blocca i download. "
                "Se il download fallisce, prova invece ad usare il bot su video con trascrizioni già disponibili."
            )
        else:
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
            else:
                await query.edit_message_text("❌ Non è stato possibile trascrivere l'audio con Whisper.")
                return
        else:
            if IS_HEROKU:
                await query.edit_message_text(
                    "❌ Download dell'audio fallito su Heroku.\n\n"
                    "YouTube blocca sistematicamente i download dai server Heroku. "
                    "Per ottenere trascrizioni, prova a:\n"
                    "1. Usare video che hanno trascrizioni già disponibili su YouTube\n"
                    "2. Usare il bot in locale anziché su Heroku\n"
                    "3. Provare con un altro video"
                )
            else:
                await query.edit_message_text("❌ Download dell'audio fallito. Prova con un altro video o utilizza un proxy.")
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
        if video_title == f"Video {video_id}":
            logger.warning(f"Could not retrieve title for video ID: {video_id}")
            # Continue anyway, just with a generic title
        
        # Get transcript
        transcript = None
        # Su Heroku, dai priorità alla trascrizione diretta di YouTube prima di tutto
        if IS_HEROKU:
            # Prima prova a ottenere la trascrizione direttamente da YouTube senza chiedere conferma
            transcript = await get_transcript_from_youtube(video_id)
            
            if transcript is None:
                # Se non è disponibile la trascrizione e siamo su Heroku, chiedi all'utente se vuole provare Whisper
                # (ma avvisa che potrebbe non funzionare)
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Sì, usa Whisper", callback_data=f"whisper_{video_id}"),
                        InlineKeyboardButton("❌ No, annulla", callback_data="cancel"),
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    "❌ Non è stato possibile ottenere la trascrizione da YouTube per questo video.\n\n"
                    "⚠️ Avviso: su Heroku, i downloads di YouTube spesso falliscono a causa delle restrizioni della piattaforma.\n\n"
                    "Vuoi comunque provare a utilizzare OpenAI Whisper? Questo richiederà il download dell'audio, "
                    "che probabilmente fallirà su Heroku, e utilizzerà crediti API aggiuntivi.",
                    reply_markup=reply_markup
                )
                return
        else:
            # Su ambiente non-Heroku, usa il comportamento normale
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
                    
        elif query.data == 'summary_openai' or query.data == 'summary_deepseek':
            # Determina quale servizio utilizzare in base al pulsante premuto
            service = "openai" if query.data == 'summary_openai' else "deepseek"
            
            # Verifica se il servizio richiesto è disponibile
            if service == "openai" and not OPENAI_API_KEY:
                await query.edit_message_text("❌ OpenAI API key non configurata. Contatta l'amministratore del bot.")
                return
            elif service == "deepseek" and not DEEPSEEK_API_KEY:
                await query.edit_message_text("❌ Deepseek API key non configurata. Contatta l'amministratore del bot.")
                return
            
            await query.edit_message_text(f"⏳ Generazione riassunto con {service.upper()} in corso...")
            
            summary = await summarize_with_ai(transcript, video_title, service)
            if summary:
                service_name = "OpenAI (gpt-4o-mini)" if service == "openai" else "Deepseek"
                response = f"📚 Riassunto ({service_name}): {video_title}\n\n{summary}"
                # Split long summaries if needed
                if len(response) > 4000:
                    chunks = [response[i:i+4000] for i in range(0, len(response), 4000)]
                    for i, chunk in enumerate(chunks):
                        await query.message.reply_text(chunk)
                else:
                    await query.message.reply_text(response)
                
                # Update status message
                await query.edit_message_text(f"✅ Riassunto con {service_name} completato!")
            else:
                await query.edit_message_text(f"❌ Non è stato possibile generare il riassunto con {service}.")
                
    except Exception as e:
        logger.error(f"Error processing request: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        # Messaggio di errore più informativo
        if "quota" in str(e).lower() or "rate" in str(e).lower():
            await query.edit_message_text(
                "❌ Errore: limite di quota API raggiunto. Riprova più tardi."
            )
        elif "auth" in str(e).lower() or "key" in str(e).lower():
            await query.edit_message_text(
                "❌ Errore di autenticazione API. Contatta l'amministratore del bot."
            )
        elif IS_HEROKU and "transcript" in str(e).lower():
            await query.edit_message_text(
                "❌ Errore nel recupero della trascrizione.\n\n"
                "Su Heroku, prova ad utilizzare solo video che hanno già trascrizioni disponibili su YouTube."
            )
        elif IS_HEROKU:
            await query.edit_message_text(
                "❌ Si è verificato un errore durante l'elaborazione su Heroku.\n\n"
                "Le limitazioni di Heroku potrebbero impedire il download dell'audio. "
                "Prova con video che hanno trascrizioni già disponibili su YouTube."
            )
        else:
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