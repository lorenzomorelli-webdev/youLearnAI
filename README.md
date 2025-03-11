# YouLearn

YouLearn è un bot Telegram che trascrive e riassume video di YouTube utilizzando le API di OpenAI.

## Caratteristiche

- Estrazione di trascrizioni direttamente da YouTube
- Trascrizione automatica con l'API Whisper di OpenAI quando i sottotitoli YouTube non sono disponibili
- Generazione di riassunti utilizzando OpenAI GPT o Deepseek
- Supporto sia per video YouTube standard che per Shorts
- Interfaccia utente Telegram semplice con pulsanti inline
- Ottimizzato per il deploy su Heroku

## Prerequisiti

- Python 3.11+
- FFmpeg (installato nell'ambiente di deploy)
- Token di Telegram Bot
- OpenAI API key (usata sia per la trascrizione che per il riassunto)
- Deepseek API key (opzionale, per riassunti alternativi)
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
DEEPSEEK_API_KEY=your_deepseek_api_key  # opzionale
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
   - `OPENAI_API_KEY`: la tua API key OpenAI (usata sia per Whisper che per GPT)
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

- **Utilizzo delle API anziché dei modelli locali**: utilizziamo l'API Whisper di OpenAI anziché eseguire localmente il modello, riducendo drasticamente la dimensione dello slug
- Nessuna dipendenza pesante come PyTorch
- Include un file `.slugignore` per escludere file non necessari
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

- La trascrizione con l'API Whisper è molto più veloce rispetto al modello locale
- La generazione del riassunto dipende dalla disponibilità dell'API key OpenAI
- Se è disponibile solo l'API key Deepseek, il bot utilizzerà quella per i riassunti
- Per video molto lunghi, la trascrizione/riassunto potrebbe essere troncato a causa dei limiti API

## Costi

- L'API Whisper di OpenAI ha un costo di circa $0.006 per minuto di audio
- L'API GPT-3.5-turbo ha un costo di circa $0.002 per 1000 token
- Calcola i costi in base all'utilizzo previsto

## Licenza

[Inserisci la tua licenza qui]

## Acknowledgments

- [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [OpenAI Whisper](https://github.com/openai/whisper)
- [OpenAI API](https://openai.com/api/)
