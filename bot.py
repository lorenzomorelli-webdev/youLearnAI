#!/usr/bin/env python3
"""
YouLearn Telegram Bot - YouTube Video Transcription and Summarization Bot
Integrates the YouLearn functionality with a Telegram bot interface.

Per attivare la modalità debug:
1. Crea un file .env nella stessa directory di questo script (o imposta le variabili d'ambiente su Heroku)
2. Aggiungi le seguenti variabili:
   DEBUG_MODE=true
   FORCE_PROXY=true (opzionale, per usare sempre il proxy)
   
La modalità debug aggiunge pulsanti di test per verificare il funzionamento
con e senza proxy, mostrando informazioni dettagliate sui tempi di risposta
e sui risultati ottenuti.
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
from youtube_transcript_api.proxies import WebshareProxyConfig, GenericProxyConfig

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

# Rileva se l'app è in esecuzione su Heroku
IS_HEROKU = "DYNO" in os.environ

# Modalità debug per test proxy in locale
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
FORCE_PROXY = os.getenv("FORCE_PROXY", "false").lower() == "true"

# Log delle impostazioni di debug
if DEBUG_MODE:
    logger.info("🔍 Modalità debug attiva")
    if FORCE_PROXY:
        logger.info("🔌 Uso forzato del proxy attivato per test")

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

# Whitelist configuration
ALLOWED_USERS = os.getenv("ALLOWED_USERS", "")

def is_user_allowed(user_id: int) -> bool:
    """
    Check if a user is allowed to use the bot based on their Telegram ID.
    
    Args:
        user_id (int): The Telegram user ID to check
        
    Returns:
        bool: True if the user is allowed, False otherwise
    """
    if not ALLOWED_USERS:
        logger.warning("ALLOWED_USERS environment variable is not set. No users are allowed.")
        return False
        
    try:
        allowed_ids = [int(id.strip()) for id in ALLOWED_USERS.split(",") if id.strip()]
        return user_id in allowed_ids
    except ValueError as e:
        logger.error(f"Error parsing ALLOWED_USERS: {e}")
        return False

# Configura il proxy solo se tutte le variabili necessarie sono presenti
if USE_PROXY and PROXY_USERNAME and PROXY_PASSWORD:
    PROXY_URL = f"http://{PROXY_USERNAME}:{PROXY_PASSWORD}@{PROXY_HOST}:{PROXY_PORT}"
    PROXIES = {
        'http': PROXY_URL,
        'https': PROXY_URL
    }
    
    # Configura il proxy a livello globale per tutte le richieste HTTP
    os.environ['HTTP_PROXY'] = PROXY_URL
    os.environ['HTTPS_PROXY'] = PROXY_URL
    
    # Configura il proxy per le librerie che usano requests
    requests.utils.default_headers()
    session = requests.Session()
    session.proxies.update(PROXIES)
    requests.Session = lambda: session
    
    logger.info(f"Proxy configurato globalmente: {PROXY_HOST}:{PROXY_PORT}")
    logger.info(f"Ambiente Heroku: {IS_HEROKU}")
    logger.info("Credenziali proxy presenti e configurate correttamente")
    
    # Verifica la configurazione del proxy
    try:
        test_response = session.get('https://api.ipify.org?format=json')
        logger.info(f"Test connessione proxy - IP utilizzato: {test_response.json().get('ip')}")
        logger.info(f"Test connessione proxy - Status code: {test_response.status_code}")
    except Exception as e:
        logger.error(f"Errore nel test del proxy: {e}")
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
    Crea una sessione requests configurata per YouTube.
    Utilizza il proxy configurato globalmente.
    """
    # Utilizziamo la sessione globale che ha già il proxy configurato
    session = requests.Session()
    
    # Imposta un User-Agent casuale
    selected_user_agent = random.choice(USER_AGENTS)
    session.headers.update({'User-Agent': selected_user_agent})
    
    logger.info(f"Sessione YouTube creata. User-Agent: {selected_user_agent}")
    
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
    Usa user-agent random e proxy configurato globalmente.
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
    
    # Il proxy è già configurato a livello globale tramite variabili d'ambiente
    
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
        # Il proxy è già configurato a livello globale, quindi non serve specificarlo qui
        return YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
    
    @staticmethod
    def list_transcripts(video_id):
        """
        Elenca le trascrizioni disponibili per un video YouTube utilizzando il proxy se configurato.
        """
        # Il proxy è già configurato a livello globale, quindi non serve specificarlo qui
        return YouTubeTranscriptApi.list_transcripts(video_id)

async def get_transcript_from_youtube(video_id: str) -> Optional[str]:
    """
    Prova a ottenere la trascrizione direttamente da YouTube.
    Usa diverse strategie e gestisce le particolarità di Heroku.
    Utilizza il proxy se configurato.
    """
    # Utilizzo del semaforo per limitare le richieste concorrenti
    async with TRANSCRIPT_SEMAPHORE:
        logger.info(f"[CONCORRENZA] Inizio richiesta trascrizione per video ID: {video_id}")
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
                logger.info(f"[CONCORRENZA] Fine richiesta trascrizione per video ID: {video_id}")
                return transcript
            except (NoTranscriptFound, TranscriptsDisabled) as e:
                logger.warning(f"Nessuna trascrizione in lingue specifiche: {e}")
                
                # Strategia 2: Prova con rilevamento automatico della lingua
                try:
                    logger.info("Tentativo trascrizione con rilevamento automatico lingua")
                    transcript_list = ProxyTranscriptApi.get_transcript(video_id)
                    transcript = ' '.join([item['text'] for item in transcript_list])
                    logger.info("Trascrizione ottenuta con rilevamento automatico lingua")
                    logger.info(f"[CONCORRENZA] Fine richiesta trascrizione per video ID: {video_id}")
                    return transcript
                except Exception as e2:
                    logger.warning(f"Rilevamento automatico lingua fallito: {e2}")
                    
                    # Strategia 3: Prova a elencare tutte le trascrizioni disponibili e seleziona la prima
                    try:
                        transcript_list = ProxyTranscriptApi.list_transcripts(video_id)
                        
                        # Prendi la prima trascrizione disponibile
                        for transcript_obj in transcript_list:
                            transcript_data = transcript_obj.fetch()
                            transcript = ' '.join([item['text'] for item in transcript_data.snippets])
                            logger.info(f"Successfully retrieved transcript in {transcript_obj.language_code}")
                            logger.info(f"[CONCORRENZA] Fine richiesta trascrizione per video ID: {video_id}")
                            return transcript
                            
                    except Exception as e3:
                        logger.warning(f"Failed to list available transcripts: {e3}")
                        # Continua con le eccezioni esterne
                        raise e3
        
        except (TranscriptsDisabled, NoTranscriptFound) as e:
            logger.warning(f"No transcript available on YouTube: {e}")
            logger.warning(f"Video URL: https://www.youtube.com/watch?v={video_id}")
            logger.info(f"[CONCORRENZA] Fallita richiesta trascrizione per video ID: {video_id}")
            return None
        except Exception as e:
            logger.error(f"Error retrieving transcript from YouTube: {e}")
            logger.error(f"Video URL: https://www.youtube.com/watch?v={video_id}")
            # Log dettagliati per il debug
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            logger.info(f"[CONCORRENZA] Fallita richiesta trascrizione per video ID: {video_id}")
            return None

async def download_audio(video_id: str) -> Optional[str]:
    """
    Download audio from a YouTube video with enhanced anti-bot measures.
    Usa user-agent diversi e tecniche avanzate di evasione del rilevamento.
    Il proxy è configurato globalmente.
    """
    try:
        logger.info(f"Avvio download audio per video ID: {video_id}")
        logger.info(f"Ambiente: {'Heroku' if IS_HEROKU else 'Non-Heroku'}")
        
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
        
        # Il proxy è già configurato a livello globale tramite variabili d'ambiente
        
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
    
    # Utilizzo del semaforo per limitare le richieste concorrenti alle API di AI
    async with SUMMARY_SEMAPHORE:
        logger.info(f"[CONCORRENZA] Inizio generazione riassunto per: {video_title[:30]}...")
        
        try:
            # Aggiungi un timeout di 60 secondi per la chiamata API
            return await asyncio.wait_for(
                _summarize_with_service(transcript, video_title, service),
                timeout=60.0
            )
        except asyncio.TimeoutError:
            logger.error(f"Timeout durante il riassunto con {service} per: {video_title[:30]}")
            logger.info(f"[CONCORRENZA] Fallita generazione riassunto (timeout) per: {video_title[:30]}")
            return None
        except Exception as e:
            logger.error(f"Error generating summary with {service}: {e}")
            logger.info(f"[CONCORRENZA] Fallita generazione riassunto per: {video_title[:30]}")
            return None

async def _summarize_with_service(transcript: str, video_title: str, service: Literal["openai", "deepseek"]) -> Optional[str]:
    """Funzione interna per generare il riassunto con un servizio specifico."""
    # Prepare the prompt
    system_prompt = "You are an expert at summarizing video content in Italian. Create a comprehensive summary of the following video transcript."
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
        logger.info(f"[CONCORRENZA] Fine generazione riassunto per: {video_title[:30]}")
        return summary
        
    except Exception as e:
        # Rilancia l'eccezione per farla gestire dal chiamante
        logger.error(f"Error in _summarize_with_service with {service}: {e}")
        raise

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
    user_id = update.effective_user.id
    logger.info(f"[CONCORRENZA] Richiesta ricevuta da utente {user_id} per processare URL YouTube")
    
    if not is_user_allowed(user_id):
        await update.message.reply_text(
            "❌ Non sei autorizzato ad utilizzare questo bot.\n\n"
            f"Il tuo Telegram ID è: {user_id}"
        )
        return
        
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
    context.user_data['using_proxy'] = FORCE_PROXY  # Usa il proxy forzatamente se attivato
    
    # Create inline keyboard with initial options
    keyboard = [
        [
            InlineKeyboardButton("📝 Trascrizione", callback_data='transcript'),
            InlineKeyboardButton("📚 Riassunto", callback_data='summary_choice')
        ]
    ]
    
    # Aggiungi opzione di test proxy in modalità debug
    if DEBUG_MODE:
        keyboard.append([
            InlineKeyboardButton("🧪 Test con Proxy", callback_data='test_proxy'),
            InlineKeyboardButton("🧪 Test senza Proxy", callback_data='test_no_proxy')
        ])
        keyboard.append([
            InlineKeyboardButton("🔍 Verifica IP con Proxy", callback_data='check_ip_proxy'),
            InlineKeyboardButton("🔍 Verifica IP senza Proxy", callback_data='check_ip_no_proxy')
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Messaggio personalizzato in base alla modalità
    message = "🎥 Cosa vuoi fare con questo video?"
    if DEBUG_MODE:
        proxy_status = "attivo" if FORCE_PROXY else "disattivato"
        message += f"\n\n🔍 Modalità debug: proxy {proxy_status} per default"
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button presses with improved concurrency management."""
    query = update.callback_query
    user_id = update.effective_user.id
    logger.info(f"[CONCORRENZA] Callback ricevuta da utente {user_id}: {query.data}")
    
    if not is_user_allowed(user_id):
        await query.answer("❌ Non sei autorizzato ad utilizzare questo bot.", show_alert=True)
        await query.edit_message_text(
            "❌ Non sei autorizzato ad utilizzare questo bot.\n\n"
            f"Il tuo Telegram ID è: {user_id}"
        )
        return

    await query.answer()
    
    video_id = context.user_data.get('video_id')
    if not video_id:
        await query.edit_message_text("❌ Sessione scaduta. Invia nuovamente il link YouTube.")
        return
    
    # Azioni che non richiedono semaforo o timeout (navigazione semplice)
    if query.data == 'summary_choice':
        # Mostra opzioni per il tipo di riassunto
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
        # Torna al menu principale
        keyboard = [
            [
                InlineKeyboardButton("📝 Trascrizione", callback_data='transcript'),
                InlineKeyboardButton("📚 Riassunto", callback_data='summary_choice')
            ]
        ]
        
        # Aggiungi opzione di test proxy in modalità debug
        if DEBUG_MODE:
            keyboard.append([
                InlineKeyboardButton("🧪 Test con Proxy", callback_data='test_proxy'),
                InlineKeyboardButton("🧪 Test senza Proxy", callback_data='test_no_proxy')
            ])
            keyboard.append([
                InlineKeyboardButton("🔍 Verifica IP con Proxy", callback_data='check_ip_proxy'),
                InlineKeyboardButton("🔍 Verifica IP senza Proxy", callback_data='check_ip_no_proxy')
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Messaggio personalizzato in base alla modalità
        message = "🎥 Cosa vuoi fare con questo video?"
        if DEBUG_MODE:
            proxy_status = "attivo" if FORCE_PROXY else "disattivato"
            message += f"\n\n🔍 Modalità debug: proxy {proxy_status} per default"
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup
        )
        return
        
    if query.data == 'cancel':
        await query.edit_message_text("⚠️ Operazione annullata.")
        return

    # Per tutte le altre operazioni che richiedono elaborazione, utilizziamo il semaforo globale e timeout
    try:
        # Usa il semaforo globale per limitare le richieste concorrenti
        # Se non riusciamo ad acquisire il semaforo entro 5 secondi, notifichiamo l'utente
        try:
            # Tenta di acquisire il semaforo con un timeout breve
            acquired = False
            async with asyncio.timeout(5.0):
                acquired = await asyncio.shield(GLOBAL_REQUEST_SEMAPHORE.acquire())
        except asyncio.TimeoutError:
            # Se non riusciamo ad acquisire il semaforo in tempo
            logger.warning(f"[CONCORRENZA] Impossibile acquisire il semaforo per utente {user_id}, troppe richieste simultanee")
            await query.edit_message_text(
                "⏳ Troppe richieste in corso. Riprova fra qualche secondo...",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]])
            )
            return
        
        # Se siamo qui, abbiamo acquisito il semaforo
        try:
            # Aggiungi un timeout per le operazioni lunghe e processa l'azione
            await query.edit_message_text("⏳ Elaborazione in corso...")
            await asyncio.wait_for(
                process_button_action(query, context, user_id, video_id),
                timeout=BUTTON_CALLBACK_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.error(f"[CONCORRENZA] Timeout durante l'elaborazione della richiesta {query.data} per utente {user_id}")
            await query.edit_message_text(
                "⏰ L'operazione sta impiegando troppo tempo ed è stata interrotta.\n"
                "Riprova più tardi o con un altro video.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]])
            )
        finally:
            # Rilascia il semaforo quando abbiamo finito
            if acquired:
                GLOBAL_REQUEST_SEMAPHORE.release()
                logger.info(f"[CONCORRENZA] Rilasciato semaforo per utente {user_id}")
                
    except Exception as e:
        logger.error(f"[CONCORRENZA] Errore durante l'elaborazione della richiesta: {e}")
        # Gestione avanzata degli errori
        error_msg = str(e).lower()
        
        if "quota" in error_msg or "rate" in error_msg:
            await query.edit_message_text(
                "❌ Errore: limite di quota API raggiunto. Riprova più tardi.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]])
            )
        elif "auth" in error_msg or "key" in error_msg:
            await query.edit_message_text(
                "❌ Errore di autenticazione API. Contatta l'amministratore del bot.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]])
            )
        else:
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Riprova", callback_data=query.data),
                    InlineKeyboardButton("❌ Annulla", callback_data='cancel')
                ],
                [InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"❌ Si è verificato un errore durante l'elaborazione.\n"
                f"Dettaglio: {str(e)[:100]}...\n"
                f"Vuoi riprovare?",
                reply_markup=reply_markup
            )
            
async def process_button_action(query, context, user_id, video_id):
    """Processa le azioni dei pulsanti in modo asincrono con gestione degli errori."""
    try:
        if query.data in ['check_ip_proxy', 'check_ip_no_proxy']:
            await process_ip_check(query, context)
            
        elif query.data in ['test_proxy', 'test_no_proxy']:
            await process_proxy_test(query, context, video_id)
            
        elif query.data == 'retry_with_proxy':
            await process_retry_with_proxy(query, context, video_id)
            
        elif query.data in ['transcript', 'summary_openai', 'summary_deepseek']:
            await process_transcript_or_summary(query, context, video_id)
            
    except Exception as e:
        # Cattura e rilancia l'eccezione per gestirla nel chiamante
        logger.error(f"Errore in process_button_action: {e}")
        raise

async def process_ip_check(query, context):
    """Processa la verifica dell'indirizzo IP."""
    # Imposta l'uso del proxy in base alla scelta
    use_proxy = (query.data == 'check_ip_proxy')
    proxy_status = "attivato" if use_proxy else "disattivato"
    await query.edit_message_text(f"⏳ Verifica IP in corso con proxy {proxy_status}...")
    
    try:
        # Configura la sessione con o senza proxy
        session = requests.Session()
        selected_user_agent = random.choice(USER_AGENTS)
        session.headers.update({'User-Agent': selected_user_agent})
        
        # Per il test senza proxy, disabilitiamo temporaneamente il proxy
        if not use_proxy:
            session.proxies.clear()
        
        # Misura il tempo di risposta
        start_time = time.time()
        response = session.get('https://api.ipify.org?format=json')
        elapsed_time = time.time() - start_time
        
        if response.status_code == 200:
            ip_data = response.json()
            ip_address = ip_data.get('ip', 'Non disponibile')
            
            # Prepara il messaggio di debug
            debug_info = (
                f"✅ Verifica IP completata!\n\n"
                f"🔌 Proxy: {proxy_status}\n"
                f"🌐 Indirizzo IP: {ip_address}\n"
                f"⏱️ Tempo di risposta: {elapsed_time:.2f} secondi\n"
                f"🖥️ Ambiente: {'Heroku' if IS_HEROKU else 'Locale/Altro'}\n\n"
            )
            
            # Aggiungi pulsanti per continuare
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Riprova con proxy", callback_data='check_ip_proxy'),
                    InlineKeyboardButton("🔄 Riprova senza proxy", callback_data='check_ip_no_proxy')
                ],
                [InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(debug_info, reply_markup=reply_markup)
        else:
            error_info = (
                f"❌ Verifica IP fallita\n\n"
                f"🔌 Proxy: {proxy_status}\n"
                f"⚠️ Status code: {response.status_code}\n"
                f"⏱️ Tempo di risposta: {elapsed_time:.2f} secondi\n"
            )
            
            # Offri opzioni per riprovare
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Riprova", callback_data=query.data),
                    InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(error_info, reply_markup=reply_markup)
    
    except Exception as e:
        # Gestisci errori durante la verifica
        error_msg = str(e)
        logger.error(f"Error during IP check: {error_msg}")
        
        error_info = (
            f"❌ Verifica IP fallita - Errore\n\n"
            f"🔌 Proxy: {proxy_status}\n"
            f"⚠️ Errore: {error_msg[:200]}...\n\n"
        )
        
        # Offri opzioni per riprovare
        keyboard = [
            [
                InlineKeyboardButton("🔄 Riprova", callback_data=query.data),
                InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(error_info, reply_markup=reply_markup)

async def process_proxy_test(query, context, video_id):
    """Processa il test del proxy."""
    # Imposta l'uso del proxy in base alla scelta
    use_proxy = (query.data == 'test_proxy')
    context.user_data['last_action'] = 'transcript'  # Default a trascrizione per test
    
    proxy_status = "attivato" if use_proxy else "disattivato"
    await query.edit_message_text(f"⏳ Test in corso con proxy {proxy_status}...")
    
    try:
        video_title = get_video_title(video_id)
        
        # Per il test senza proxy, disabilitiamo temporaneamente il proxy
        if not use_proxy:
            # Salva le variabili d'ambiente originali
            original_http_proxy = os.environ.get('HTTP_PROXY')
            original_https_proxy = os.environ.get('HTTPS_PROXY')
            
            # Rimuovi temporaneamente le variabili d'ambiente del proxy
            if 'HTTP_PROXY' in os.environ:
                del os.environ['HTTP_PROXY']
            if 'HTTPS_PROXY' in os.environ:
                del os.environ['HTTPS_PROXY']
        
        # Ottieni la trascrizione
        start_time = time.time()
        transcript = await get_transcript_from_youtube(video_id)
        elapsed_time = time.time() - start_time
        
        # Ripristina le variabili d'ambiente del proxy se necessario
        if not use_proxy and original_http_proxy:
            os.environ['HTTP_PROXY'] = original_http_proxy
        if not use_proxy and original_https_proxy:
            os.environ['HTTPS_PROXY'] = original_https_proxy
        
        if transcript:
            # Mostra solo un estratto della trascrizione per il test
            transcript_preview = transcript[:200] + "..." if len(transcript) > 200 else transcript
            
            # Prepara il messaggio di debug
            debug_info = (
                f"✅ Test completato con successo!\n\n"
                f"🔌 Proxy: {proxy_status}\n"
                f"⏱️ Tempo impiegato: {elapsed_time:.2f} secondi\n"
                f"📊 Lunghezza trascrizione: {len(transcript)} caratteri\n\n"
                f"📝 Anteprima trascrizione:\n{transcript_preview}\n\n"
            )
            
            # Aggiungi pulsanti per continuare
            keyboard = [
                [
                    InlineKeyboardButton("📝 Trascrizione completa", callback_data='transcript'),
                    InlineKeyboardButton("📚 Riassunto", callback_data='summary_choice')
                ],
                [InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(debug_info, reply_markup=reply_markup)
        else:
            # Gestisci il caso in cui la trascrizione non è disponibile
            error_info = (
                f"❌ Test fallito - Nessuna trascrizione disponibile\n\n"
                f"🔌 Proxy: {proxy_status}\n"
                f"⏱️ Tempo impiegato: {elapsed_time:.2f} secondi\n\n"
            )
            
            # Offri opzioni per riprovare
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Riprova con proxy", callback_data='test_proxy'),
                    InlineKeyboardButton("🔄 Riprova senza proxy", callback_data='test_no_proxy')
                ],
                [InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(error_info, reply_markup=reply_markup)
    
    except Exception as e:
        # Gestisci errori durante il test
        error_msg = str(e)
        logger.error(f"Error during proxy test: {error_msg}")
        
        error_info = (
            f"❌ Test fallito - Errore\n\n"
            f"🔌 Proxy: {proxy_status}\n"
            f"⚠️ Errore: {error_msg[:200]}...\n\n"
        )
        
        # Offri opzioni per riprovare
        keyboard = [
            [
                InlineKeyboardButton("🔄 Riprova con proxy", callback_data='test_proxy'),
                InlineKeyboardButton("🔄 Riprova senza proxy", callback_data='test_no_proxy')
            ],
            [InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(error_info, reply_markup=reply_markup)

async def process_retry_with_proxy(query, context, video_id):
    """Processa il retry con proxy."""
    await query.edit_message_text("⏳ Riprovo l'operazione...")
    
    try:
        video_title = get_video_title(video_id)
        last_action = context.user_data.get('last_action')
        
        # Ottieni la trascrizione
        transcript = await get_transcript_from_youtube(video_id)
        
        if transcript is None:
            await query.edit_message_text(
                "❌ Non è stato possibile ottenere la trascrizione.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]])
            )
            return
        
        # Procedi in base all'azione originale
        if last_action == 'transcript':
            # Invia la trascrizione
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
        
        elif last_action in ['summary_openai', 'summary_deepseek']:
            service = "openai" if last_action == 'summary_openai' else "deepseek"
            
            # Verifica disponibilità API key
            if service == "openai" and not OPENAI_API_KEY:
                await query.edit_message_text(
                    "❌ OpenAI API key non configurata. Contatta l'amministratore del bot.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]])
                )
                return
            elif service == "deepseek" and not DEEPSEEK_API_KEY:
                await query.edit_message_text(
                    "❌ Deepseek API key non configurata. Contatta l'amministratore del bot.",
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
        logger.error(f"Error processing retry request: {e}")
        await query.edit_message_text(
            "❌ Si è verificato un errore durante l'elaborazione della richiesta.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]])
        )

async def process_transcript_or_summary(query, context, video_id):
    """Processa la richiesta di trascrizione o riassunto."""
    context.user_data['last_action'] = query.data
    
    try:
        video_title = get_video_title(video_id)
        
        # Ottieni la trascrizione
        transcript = None
        try:
            transcript = await get_transcript_from_youtube(video_id)
        except Exception as e:
            logger.error(f"Error getting transcript: {e}")
            # Offri l'opzione di riprovare
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Riprova", callback_data='retry_with_proxy'),
                    InlineKeyboardButton("❌ Annulla", callback_data='cancel')
                ],
                [InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"❌ Non è stato possibile ottenere la trascrizione.\nErrore: {str(e)[:100]}...\n"
                "Vuoi riprovare?",
                reply_markup=reply_markup
            )
            return

        if transcript is None:
            # Offri l'opzione di riprovare
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Riprova", callback_data='retry_with_proxy'),
                    InlineKeyboardButton("❌ Annulla", callback_data='cancel')
                ],
                [InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "❌ Non è stato possibile ottenere la trascrizione.\n"
                "Vuoi riprovare?",
                reply_markup=reply_markup
            )
            return

        if query.data == 'transcript':
            # Invia la trascrizione
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
            
            # Verifica disponibilità API key
            if service == "openai" and not OPENAI_API_KEY:
                await query.edit_message_text(
                    "❌ OpenAI API key non configurata. Contatta l'amministratore del bot.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]])
                )
                return
            elif service == "deepseek" and not DEEPSEEK_API_KEY:
                await query.edit_message_text(
                    "❌ Deepseek API key non configurata. Contatta l'amministratore del bot.",
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
        logger.error(f"Error in process_transcript_or_summary: {e}")
        # Rilancia l'eccezione per gestirla nel chiamante
        raise

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log Errors caused by Updates."""
    logger.error(f"Update {update} caused error {context.error}")
    
    # Verifica se l'errore è relativo a più istanze del bot in esecuzione
    if "terminated by other getUpdates request" in str(context.error):
        logger.error("ERRORE CRITICO: Un'altra istanza del bot è già in esecuzione. Termina tutte le altre istanze e riavvia.")
        return
    
    # Gestione specifica dei timeout
    if isinstance(context.error, asyncio.TimeoutError) or "Timed out" in str(context.error):
        logger.error(f"Rilevato timeout per {update}")
        if update and update.effective_message:
            keyboard = [[InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.effective_message.reply_text(
                "⏰ L'operazione ha richiesto troppo tempo ed è stata interrotta.\n"
                "Riprova più tardi o con un video più breve.",
                reply_markup=reply_markup
            )
        return
        
    # Verifica che update non sia None prima di accedere ai suoi attributi
    if update and update.effective_message:
        # Messaggi di errore specifici per tipologia
        error_msg = str(context.error).lower()
        
        if "quota" in error_msg or "rate" in error_msg:
            await update.effective_message.reply_text(
                "❌ Errore: limite di quota API raggiunto. Riprova più tardi.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]])
            )
        elif "auth" in error_msg or "key" in error_msg or "credentials" in error_msg:
            await update.effective_message.reply_text(
                "❌ Errore di autenticazione API. Contatta l'amministratore del bot.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]])
            )
        else:
            await update.effective_message.reply_text(
                "❌ Si è verificato un errore durante l'elaborazione della richiesta.\n"
                "Per favore, riprova più tardi.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Indietro", callback_data='back_to_main')]])
            )

def main() -> None:
    """Start the bot with advanced concurrency settings."""
    # Create the Application with concurrent updates enabled
    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .concurrent_updates(True)  # Abilita aggiornamenti concorrenti
        .build()
    )

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_youtube_url))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Add error handler
    application.add_error_handler(error_handler)

    # Log startup with concurrency info
    logger.info("Starting bot in polling mode with concurrent updates enabled")
    
    # Start the Bot with optimized polling settings (versione sincrona)
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,  # Ignora gli update pendenti all'avvio
    )

if __name__ == '__main__':
    # Avvia il bot senza gestione asincrona esplicita
    main() 