# Site Monitor

Monitora uptime e velocità di più siti, gratis, con GitHub Actions. Avvisi su Telegram, dashboard su GitHub Pages.

- **Ogni 5 minuti** (`check.yml`): richiesta a ogni URL di `config.json`; registra stato, TTFB e tempo totale; controlla anche un testo atteso nella pagina.
- **Ogni giorno** (`daily.yml`): PageSpeed Insights (mobile: punteggio, LCP, TBT, CLS) e scadenza del certificato SSL.
- **Avvisi Telegram**: sito giù (dopo 2 controlli falliti consecutivi), tornato online, pagina lenta (> `slow_ms`), SSL in scadenza.
- **Dashboard**: `docs/index.html`, legge i dati da `docs/data/`.

## Configurazione

1. Crea un repository **pubblico** su GitHub (nel privato 2000 min/mese non bastano per un controllo ogni 5 minuti) e carica questa cartella.
2. Telegram: scrivi a `@BotFather` → `/newbot` per ottenere il token; scrivi un messaggio al bot e apri `https://api.telegram.org/bot<TOKEN>/getUpdates` per leggere il tuo `chat.id`.
3. *Settings → Secrets and variables → Actions*, aggiungi:
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `PSI_API_KEY` (gratuita: console Google Cloud → abilita "PageSpeed Insights API"; senza chiave l'API risponde 429)
4. *Settings → Pages*: sorgente `main`, cartella `/docs`.
5. *Actions → check → Run workflow* per il primo giro.

## Aggiungere un sito

Modifica `config.json`:

```json
{ "name": "Cliente", "urls": [{ "url": "https://esempio.it/", "expect_text": "Testo atteso" }], "psi_url": "https://esempio.it/" }
```

`expect_status` (default 200) e `expect_text` sono facoltativi per ogni URL.

## Prova in locale

```
python monitor.py check
python monitor.py daily
```

Poi apri `docs/index.html` con un server statico (`python -m http.server -d docs`).

## Note

- GitHub può ritardare i cron di qualche minuto nelle ore di punta: l'intervallo reale è 5–10 minuti.
- Dopo 60 giorni senza commit GitHub disattiva i workflow pianificati; i commit dei dati lo evitano.
- I dati dei controlli vengono conservati per `keep_days` giorni.
