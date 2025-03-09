# YouLearn

YouLearn è un bot Telegram che trascrive e riassume video di YouTube utilizzando sia OpenAI GPT che Deepseek.

## Caratteristiche

- Estrazione di trascrizioni direttamente da YouTube
- Trascrizione automatica con Whisper quando le sottotitoli YouTube non sono disponibili
- Generazione di riassunti utilizzando OpenAI GPT o Deepseek
- Supporto sia per video YouTube standard che per Shorts
- Interfaccia utente Telegram semplice con pulsanti inline
- Ottimizzato per il deploy su Heroku

## Prerequisiti

- Python 3.11+
- FFmpeg (installato nell'ambiente di deploy)
- Token di Telegram Bot
- OpenAI API key e/o Deepseek API key
- Account Heroku (per il deploy)

## Installazione Locale

1. Clona il repository:

```bash
git clone <repository-url>
cd youlearn
```

2. Installa le dipendenze richieste:

```bash
pip install -r requirements.txt
```

3. Crea un file `.env` nella root del progetto e aggiungi le tue chiavi API:

```env
TELEGRAM_TOKEN=your_telegram_bot_token
OPENAI_API_KEY=your_openai_api_key
DEEPSEEK_API_KEY=your_deepseek_api_key
```

4. Avvia il bot:

```bash
python bot.py
```

## Deploy su Heroku

Il progetto è ottimizzato per Heroku, con particolare attenzione alla dimensione dello "slug" (limite 500 MB).

### Setup in Heroku

1. Crea una nuova app su Heroku
2. Configura le variabili d'ambiente necessarie:

   - `TELEGRAM_TOKEN`: il token del tuo bot Telegram
   - `OPENAI_API_KEY`: la tua API key OpenAI
   - `DEEPSEEK_API_KEY`: la tua API key Deepseek (opzionale)

3. Collega il repository a Heroku e deploita:

```bash
# Dopo esserti loggato con heroku login
heroku git:remote -a your-heroku-app-name
git push heroku main
```

4. Attiva il worker:

```bash
heroku ps:scale worker=1
```

### Ottimizzazioni per Heroku

Questo progetto include varie ottimizzazioni per Heroku:

- Usa la versione CPU-only di PyTorch per ridurre la dimensione
- Utilizza un modello Whisper più piccolo ("tiny") per risparmiare memoria
- Include un file `.slugignore` per escludere file non necessari
- Carica il modello Whisper solo quando necessario (lazy loading)
- Utilizza cartelle temporanee di sistema per file temporanei
- Rimuove automaticamente i file audio dopo la trascrizione

## Utilizzo del Bot

1. Avvia il bot su Telegram cercandolo per nome
2. Invia il comando `/start` per iniziare
3. Invia l'URL di un video YouTube
4. Scegli "Trascrizione" o "Riassunto" dai pulsanti
5. Attendi l'elaborazione e ricevi il risultato

Il bot supporta:

- Video YouTube standard
- YouTube Shorts
- Gestione di trascrizioni lunghe (inviate in più messaggi)

## Note

- La trascrizione con Whisper può richiedere tempo
- La generazione del riassunto dipende dalla disponibilità delle API key
- Se è disponibile solo una delle due API key (OpenAI o Deepseek), il bot utilizzerà quella disponibile
- Per video molto lunghi, la trascrizione/riassunto potrebbe essere troncato

## Licenza

[Inserisci la tua licenza qui]

## Acknowledgments

- [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [OpenAI Whisper](https://github.com/openai/whisper)
- [OpenAI API](https://openai.com/api/)
