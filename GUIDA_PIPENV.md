# Guida all'utilizzo dell'ambiente Pipenv

Questo progetto utilizza Pipenv per gestire le dipendenze Python in un ambiente virtuale isolato. Ecco come utilizzarlo.

## Attivazione dell'ambiente virtuale

Per attivare l'ambiente virtuale, esegui:

```powershell
pipenv shell
```

Questo comando apre una nuova shell con l'ambiente virtuale attivato. Tutte le dipendenze installate saranno disponibili in questa shell.

## Esecuzione di comandi nell'ambiente virtuale senza attivarlo

Se vuoi eseguire un comando singolo nell'ambiente virtuale senza attivarlo completamente:

```powershell
pipenv run python youlearn.py https://www.youtube.com/watch?v=VIDEO_ID [--summarize]
```

## Installazione di nuove dipendenze

Se hai bisogno di installare nuove dipendenze:

```powershell
pipenv install nome_pacchetto
```

Per installare dipendenze solo per lo sviluppo (come strumenti di test):

```powershell
pipenv install --dev nome_pacchetto
```

## Disattivazione dell'ambiente virtuale

Per uscire dall'ambiente virtuale attivato, esegui:

```powershell
exit
```

## Posizione dell'ambiente virtuale

L'ambiente virtuale è memorizzato in una cartella gestita da Pipenv, normalmente nella directory utente sotto `.virtualenvs`. Non è necessario conoscere la posizione esatta poiché Pipenv gestisce tutto automaticamente.

## Nota sull'API di OpenAI

Per utilizzare la funzionalità di riassunto, è necessario creare un file `.env` nella directory del progetto con il seguente contenuto:

```
OPENAI_API_KEY=la_tua_api_key_di_openai
```

## Prerequisiti esterni

Ricorda che FFmpeg è necessario per l'estrazione audio. Consultare `INSTALL_FFMPEG.md` per le istruzioni d'installazione.
