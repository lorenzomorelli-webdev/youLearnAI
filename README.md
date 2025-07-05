# YouLearn Bot

YouLearn è un bot Telegram che ti permette di ottenere trascrizioni e riassunti di video YouTube in modo semplice e veloce.

## Funzionalità

-   📝 Trascrizione automatica di video YouTube
-   📚 Generazione di riassunti utilizzando AI (OpenAI GPT-4 o Deepseek)
-   🎥 Supporto per video standard e Shorts
-   🔒 Accesso limitato a utenti autorizzati

## Come Ottenere l'Accesso

Il bot è disponibile solo per utenti autorizzati. Per richiedere l'accesso:

1. **Trova il tuo Telegram ID** usando uno dei seguenti metodi:

    - Avvia il bot [@userinfobot](https://t.me/userinfobot) o [@myidbot](https://t.me/myidbot) su Telegram
    - Invia un messaggio al nostro bot - ti risponderà con il tuo ID anche se non sei autorizzato
    - In alternativa, puoi trovare il tuo ID visitando [web.telegram.org](https://web.telegram.org), accedendo al tuo account e cercando il numero nella barra degli indirizzi

2. **Contatta l'amministratore** fornendo:
    - Il tuo Telegram ID
    - Il motivo per cui desideri utilizzare il bot
    - Il tuo nome/username Telegram

## Configurazione (per amministratori)

Per configurare il bot, è necessario impostare le seguenti variabili d'ambiente:

```bash
# Configurazione base
TELEGRAM_TOKEN=your_bot_token
OPENAI_API_KEY=your_openai_api_key
DEEPSEEK_API_KEY=your_deepseek_api_key

# Whitelist utenti (ID separati da virgola)
ALLOWED_USERS=123456789,987654321,200074582

# Configurazione proxy (opzionale)
USE_PROXY=false
PROXY_USERNAME=your_proxy_username
PROXY_PASSWORD=your_proxy_password
PROXY_HOST=gate.smartproxy.com
PROXY_PORT=10001

# Modalità debug (opzionale)
DEBUG_MODE=false
FORCE_PROXY=false
```

## Come Usare il Bot

1. Avvia il bot su Telegram
2. Invia un link YouTube (video standard o Shorts)
3. Scegli se vuoi:
    - 📝 La trascrizione del video
    - 📚 Un riassunto del contenuto

## Note Tecniche

-   Il bot utilizza la YouTube Transcript API per ottenere le trascrizioni
-   I riassunti possono essere generati usando OpenAI GPT-4 o Deepseek
-   È possibile configurare un proxy per aggirare eventuali limitazioni geografiche
-   La modalità debug permette di testare il funzionamento con e senza proxy

## Configurazione

### Prerequisiti

-   Python 3.8+
-   Un token per un bot Telegram (ottenibile tramite [@BotFather](https://t.me/BotFather))
-   Una chiave API OpenAI (per la trascrizione con Whisper e i riassunti con gpt-4o-mini)
-   Opzionale: Una chiave API Deepseek (per riassunti alternativi)
-   Opzionale: Un account SmartProxy per bypassare i blocchi di YouTube

### Installazione

1. Clona il repository:

    ```
    git clone https://github.com/tuousername/youlearn-bot.git
    cd youlearn-bot
    ```

2. Installa le dipendenze:

    ```
    pip install -r requirements.txt
    ```

3. Copia il file `.env.example` in `.env` e inserisci le tue credenziali:

    ```
    cp .env.example .env
    ```

4. Modifica il file `.env` con le tue chiavi API e configurazioni.

### Configurazione del Proxy

Il bot supporta l'uso di SmartProxy per bypassare i blocchi di YouTube. Per configurarlo:

1. Ottieni un account su [SmartProxy](https://smartproxy.com/)
2. Configura le seguenti variabili nel file `.env`:
    ```
    USE_PROXY=true
    PROXY_USERNAME=your_username
    PROXY_PASSWORD=your_password
    PROXY_HOST=gate.smartproxy.com
    PROXY_PORT=10001
    ```

Il proxy verrà utilizzato solo per le chiamate a YouTube (download trascrizioni e audio), risparmiando traffico.

### Deployment su Heroku

1. Crea un'app su Heroku
2. Configura le variabili d'ambiente nell'interfaccia di Heroku (Settings > Config Vars)
3. Collega il repository GitHub e deploy

## Utilizzo

1. Avvia il bot:

    ```
    pipenv shell
    python bot.py
    ```

2. Invia un link YouTube al bot su Telegram
3. Scegli tra le opzioni disponibili:
    - 📝 **Trascrizione**: ottieni la trascrizione completa del video
    - 📚 **Riassunto OpenAI**: genera un riassunto utilizzando il modello gpt-4o-mini di OpenAI
    - 📚 **Riassunto Deepseek**: genera un riassunto utilizzando il modello di Deepseek

## Modelli AI Supportati

Il bot supporta due modelli AI per la generazione di riassunti:

1. **OpenAI (gpt-4o-mini)**: Un modello potente e compatto di OpenAI, ottimo per riassunti dettagliati e ben strutturati.
2. **Deepseek**: Un'alternativa che può offrire prospettive diverse o essere utilizzata quando OpenAI non è disponibile.

Puoi configurare uno o entrambi i modelli. Il bot mostrerà solo le opzioni per i modelli configurati.

## Note per Heroku

Su Heroku, YouTube tende a bloccare i download di audio. Per questo motivo:

-   Il bot tenterà prima di ottenere le trascrizioni direttamente da YouTube
-   L'uso del proxy può aiutare a superare questi blocchi
-   Per i video senza trascrizioni disponibili, il download dell'audio potrebbe comunque fallire

## Licenza

MIT

## Caratteristiche

-   Estrazione di trascrizioni direttamente da YouTube
-   Trascrizione automatica con l'API Whisper di OpenAI quando i sottotitoli YouTube non sono disponibili
-   Generazione di riassunti utilizzando OpenAI GPT o Deepseek
-   Supporto sia per video YouTube standard che per Shorts
-   Interfaccia utente Telegram semplice con pulsanti inline
-   Ottimizzato per il deploy su Heroku

## Prerequisiti

-   Python 3.11+
-   FFmpeg (installato nell'ambiente di deploy)
-   Token di Telegram Bot
-   OpenAI API key (usata sia per la trascrizione che per il riassunto)
-   Deepseek API key (opzionale, per riassunti alternativi)
-   Account Heroku (per il deploy)

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

-   **Utilizzo delle API anziché dei modelli locali**: utilizziamo l'API Whisper di OpenAI anziché eseguire localmente il modello, riducendo drasticamente la dimensione dello slug
-   Nessuna dipendenza pesante come PyTorch
-   Include un file `.slugignore` per escludere file non necessari
-   Utilizza cartelle temporanee di sistema per file temporanei
-   Rimuove automaticamente i file audio dopo la trascrizione

## Utilizzo del Bot

1. Avvia il bot su Telegram cercandolo per nome
2. Invia il comando `/start` per iniziare
3. Invia l'URL di un video YouTube
4. Scegli "Trascrizione" o "Riassunto" dai pulsanti
5. Attendi l'elaborazione e ricevi il risultato

Il bot supporta:

-   Video YouTube standard
-   YouTube Shorts
-   Gestione di trascrizioni lunghe (inviate in più messaggi)

## Note

-   La trascrizione con l'API Whisper è molto più veloce rispetto al modello locale
-   La generazione del riassunto dipende dalla disponibilità dell'API key OpenAI
-   Se è disponibile solo l'API key Deepseek, il bot utilizzerà quella per i riassunti
-   Per video molto lunghi, la trascrizione/riassunto potrebbe essere troncato a causa dei limiti API

## Costi

-   L'API Whisper di OpenAI ha un costo di circa $0.006 per minuto di audio
-   L'API GPT-3.5-turbo ha un costo di circa $0.002 per 1000 token
-   Calcola i costi in base all'utilizzo previsto

## Licenza

[Inserisci la tua licenza qui]

## Acknowledgments

-   [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api)
-   [yt-dlp](https://github.com/yt-dlp/yt-dlp)
-   [OpenAI Whisper](https://github.com/openai/whisper)
-   [OpenAI API](https://openai.com/api/)
