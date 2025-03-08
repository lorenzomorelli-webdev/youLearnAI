# Come installare FFmpeg su Windows

FFmpeg è necessario per l'estrazione dell'audio dai video YouTube. Segui questi passaggi per installarlo su Windows:

## Metodo 1: Installazione manuale

1. Scarica FFmpeg da [ffmpeg.org](https://ffmpeg.org/download.html#build-windows) o direttamente da [GitHub Releases](https://github.com/GyanD/codexffmpeg/releases/)
2. Scarica la versione "git-full" (ad esempio ffmpeg-git-full.7z)
3. Estrai il file scaricato
4. Copia tutti i file dalla cartella "bin" estratta in una cartella di tua scelta (ad esempio C:\FFmpeg\bin)
5. Aggiungi il percorso alla cartella bin al PATH di sistema:
   - Cerca "Variabili d'ambiente" in Windows
   - Fai clic su "Variabili d'ambiente..."
   - Nella sezione "Variabili di sistema", seleziona "Path" e fai clic su "Modifica"
   - Fai clic su "Nuovo" e aggiungi il percorso alla cartella bin (ad esempio C:\FFmpeg\bin)
   - Fai clic su "OK" per chiudere tutte le finestre
6. Riavvia qualsiasi prompt dei comandi aperto affinché le modifiche abbiano effetto

## Metodo 2: Installazione con Scoop (consigliato)

Se hai [Scoop](https://scoop.sh/) installato:

```powershell
scoop install ffmpeg
```

## Metodo 3: Installazione con Chocolatey

Se hai [Chocolatey](https://chocolatey.org/) installato:

```powershell
choco install ffmpeg
```

## Verifica dell'installazione

Dopo l'installazione, verifica che FFmpeg sia disponibile aprendo un prompt dei comandi e digitando:

```
ffmpeg -version
```

Dovresti vedere le informazioni sulla versione di FFmpeg installata.

## Note

- È necessario riavviare il prompt dei comandi dopo l'installazione per utilizzare FFmpeg.
- Se stai usando l'ambiente virtuale pipenv, assicurati di riavviare anche la shell pipenv dopo l'installazione di FFmpeg.
