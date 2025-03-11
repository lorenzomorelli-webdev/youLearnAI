# Guida alla creazione del file cookies.txt per YouLearn Bot

Per migliorare l'affidabilità del bot e superare le restrizioni anti-bot di YouTube, puoi creare un file `cookies.txt` contenente i cookie della tua sessione di YouTube. Ecco come fare:

## Metodo 1: Usando l'estensione "Get cookies.txt" per Chrome/Firefox

1. Installa l'estensione "Get cookies.txt":

   - Per Chrome: [Get cookies.txt](https://chrome.google.com/webstore/detail/get-cookiestxt/bgaddhkoddajcdgocldbbfleckgcbcid)
   - Per Firefox: [Cookie Quick Manager](https://addons.mozilla.org/it/firefox/addon/cookie-quick-manager/)

2. Accedi al tuo account YouTube (youtube.com)

3. Apri l'estensione e esporta i cookie per il dominio "youtube.com" (e opzionalmente anche "google.com")

4. Salva il file col nome `cookies.txt` nella stessa directory del bot

## Metodo 2: Usando yt-dlp per creare il file cookies

1. Installa yt-dlp sul tuo computer se non l'hai già fatto:

   ```
   pip install yt-dlp
   ```

2. Esegui questo comando per generare un file cookie:

   ```
   yt-dlp --cookies-from-browser chrome
   ```

   - Sostituisci `chrome` con `firefox`, `opera`, o `edge` a seconda del browser che utilizzi

3. Copia il file generato nella directory del bot e rinominalo in `cookies.txt`

## Note importanti

- **Sicurezza**: Il file dei cookie contiene informazioni di accesso sensibili. Non condividerlo con nessuno e non includerlo in repository pubblici.

- **Scadenza**: I cookie possono scadere dopo un certo periodo. Se il bot inizia a ricevere nuovamente errori, potrebbe essere necessario rigenerare il file dei cookie.

- **Aggiornamento periodico**: Anche se non scadessero, è buona prassi aggiornare il file dei cookie ogni 2-3 settimane per evitare problemi.

- **Formato**: Assicurati che il file sia in formato Netscape/Mozilla. Il formato corretto dovrebbe avere una riga di intestazione come:

  ```
  # Netscape HTTP Cookie File
  ```

  seguita da righe che contengono i cookie.

- **Deployment**: Se esegui il bot su Heroku o altri servizi cloud, dovrai caricare il file dei cookie insieme al codice del bot.

## Verifica

Se il file è posizionato correttamente, all'avvio del bot dovresti vedere un messaggio di log:

```
Cookie file trovato: /percorso/al/tuo/cookies.txt
```

Se invece vedi:

```
Cookie file non trovato in: /percorso/al/tuo/cookies.txt
```

significa che il file non è stato posizionato correttamente o ha un nome diverso.
