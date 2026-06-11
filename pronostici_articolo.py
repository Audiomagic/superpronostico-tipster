import requests
import os
import json
import time
from datetime import datetime, timezone, timedelta

# ─── CONFIG ──────────────────────────────────────────────────
BOT_TOKEN       = os.environ["BOT_TOKEN"]
CHAT_ID         = os.environ["CHAT_ID"]
APIFOOTBALL_KEY = os.environ["APIFOOTBALL_KEY"]
GEMINI_API_KEYS = [k for k in [
    os.environ.get("GEMINI_API_KEY"),
    os.environ.get("GEMINI_API_KEY_2"),
    os.environ.get("GEMINI_API_KEY_3"),
] if k]

GEMINI_MODELS = [
    "gemini-2.0-flash", "gemini-2.0-flash-lite",
    "gemini-2.5-flash", "gemini-flash-latest",
]

# Campionati prioritari in ordine di importanza
TOP_LEAGUES = [1, 2, 3, 135, 39, 140, 78, 61]
LEAGUE_PRIORITY = {lid: i for i, lid in enumerate(TOP_LEAGUES)}

def get_now_it():
    return datetime.now(timezone(timedelta(hours=2)))

def chiedi_gemini(prompt):
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 2000}
    }
    for key in GEMINI_API_KEYS:
        for model in GEMINI_MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            try:
                r = requests.post(url, json=body, timeout=60)
                if r.status_code == 200:
                    return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                elif r.status_code == 429:
                    continue
            except:
                continue
    return None

def fetch_odds_bulk(fixture_ids, api_key):
    """Fetcha le quote per una lista di fixture in UNA sola chiamata per fixture."""
    headers = {"x-apisports-key": api_key}
    odds_map = {}
    for fid in fixture_ids:
        ro = requests.get("https://v3.football.api-sports.io/odds",
            headers=headers,
            params={"fixture": fid})
        data = ro.json().get("response", [])
        if data:
            for bk in data[0].get("bookmakers", []):
                for bet in bk.get("bets", []):
                    if bet["name"] == "Match Winner":
                        o1 = ox = o2 = None
                        for v in bet["values"]:
                            if v["value"] == "Home": o1 = v["odd"]
                            elif v["value"] == "Draw": ox = v["odd"]
                            elif v["value"] == "Away": o2 = v["odd"]
                        odds_map[fid] = {"1": o1, "X": ox, "2": o2}
                        break
                if fid in odds_map:
                    break
        time.sleep(0.2)
    return odds_map

def fetch_partite_oggi():
    """Fetcha tutte le partite dei campionati top di oggi."""
    headers = {"x-apisports-key": APIFOOTBALL_KEY}
    now_it = get_now_it()
    date_str = now_it.strftime("%Y-%m-%d")

    print(f"Cerco partite per {date_str}...")
    r = requests.get("https://v3.football.api-sports.io/fixtures",
        headers=headers,
        params={"date": date_str, "timezone": "Europe/Rome"})

    if r.status_code != 200:
        print(f"API-Football errore: {r.status_code}")
        return []

    all_fixtures = r.json().get("response", [])
    print(f"Totale fixture oggi: {len(all_fixtures)}")

    # Filtra campionati top — includi NS (non iniziate) e anche FT (finite, per analisi)
    # Ma escludi quelle già iniziate da più di 30 minuti
    partite_raw = []
    for f in all_fixtures:
        if f["league"]["id"] not in TOP_LEAGUES:
            continue
        status = f["fixture"]["status"]["short"]
        # Includi: non iniziate, da iniziare, o che iniziano oggi
        if status not in ["NS", "TBD", "PST"]:
            continue
        partite_raw.append(f)

    print(f"Partite nei campionati top (NS/TBD): {len(partite_raw)}")

    if not partite_raw:
        print("Nessuna partita trovata. Controllo leagues presenti oggi:")
        leagues_today = {}
        for f in all_fixtures:
            lid = f["league"]["id"]
            lname = f["league"]["name"]
            leagues_today[lid] = lname
        for lid, lname in sorted(leagues_today.items())[:20]:
            print(f"  [{lid}] {lname}")
        return []

    # Fetch quote in bulk (1 chiamata per fixture)
    fixture_ids = [f["fixture"]["id"] for f in partite_raw]
    print(f"Fetch quote per {len(fixture_ids)} partite...")
    odds_map = fetch_odds_bulk(fixture_ids, APIFOOTBALL_KEY)

    # Assembla risultato finale
    partite = []
    for f in partite_raw:
        fid = f["fixture"]["id"]
        odds = odds_map.get(fid, {})
        partite.append({
            "id": fid,
            "home": f["teams"]["home"]["name"],
            "away": f["teams"]["away"]["name"],
            "orario": f["fixture"]["date"][11:16],
            "league": f["league"]["name"],
            "league_id": f["league"]["id"],
            "odds_1": odds.get("1") or "N/D",
            "odds_x": odds.get("X") or "N/D",
            "odds_2": odds.get("2") or "N/D",
        })
        print(f"  {f['fixture']['date'][11:16]} {f['teams']['home']['name']} vs {f['teams']['away']['name']} [{f['league']['name']}] 1={odds.get('1','N/D')} X={odds.get('X','N/D')} 2={odds.get('2','N/D')}")

    # Ordina per priorità lega poi orario
    partite.sort(key=lambda x: (LEAGUE_PRIORITY.get(x["league_id"], 99), x["orario"]))
    return partite

def genera_articolo(partite, now_it):
    partite_testo = ""
    for i, p in enumerate(partite, 1):
        q1 = f"@{p['odds_1']}" if p['odds_1'] != "N/D" else ""
        qx = f"@{p['odds_x']}" if p['odds_x'] != "N/D" else ""
        q2 = f"@{p['odds_2']}" if p['odds_2'] != "N/D" else ""
        partite_testo += f"{i}. {p['home']} vs {p['away']} ({p['league']}) ore {p['orario']}\n"
        if p['odds_1'] != "N/D":
            partite_testo += f"   Quote: 1={p['odds_1']}  X={p['odds_x']}  2={p['odds_2']}\n"
        partite_testo += "\n"

    prompt = f"""Sei un analista calcistico professionista italiano che scrive per il canale Telegram SuperPronostico.
Oggi e {now_it.strftime('%A %d %B %Y')}.

Scrivi un post Telegram professionale con l'analisi delle partite di oggi.
Tono: autorevole, appassionato, da vero esperto calcistico italiano.

PARTITE DI OGGI:
{partite_testo}

STRUTTURA DEL POST:
1. Intestazione con emoji calcio, data e titolo tipo "LE ANALISI DI OGGI ⚽"
2. Per ogni partita:
   - *Home vs Away* (orario) — lega in corsivo
   - 2-3 righe di analisi: contesto partita, punti di forza, fattore chiave
   - *Pronostico: [segno] [motivazione breve]* con quota se disponibile
   - Se quote disponibili: una riga Quote: 1=X X=X 2=X
   - Riga separatrice ——————
3. Chiusura: invito a seguire il canale + disclaimer gioco responsabile

REGOLE FORMATO TELEGRAM:
- *testo* per grassetto
- _testo_ per corsivo  
- Emoji vivaci ⚽🔥📊💡🎯
- Massimo 3800 caratteri totali
- Solo italiano
- Solo il testo del post, nient'altro"""

    print("Gemini sta scrivendo l'articolo...")
    return chiedi_gemini(prompt)

def pubblica_telegram(testo):
    if len(testo) > 4096:
        testo = testo[:4090] + "..."

    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": testo, "parse_mode": "Markdown"}
    )
    result = r.json()
    if result.get("ok"):
        print(f"Telegram OK — message_id: {result['result']['message_id']}")
        return result["result"]["message_id"]

    # Fallback senza markdown
    r2 = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": testo}
    )
    result2 = r2.json()
    if result2.get("ok"):
        print(f"Telegram OK (no md) — message_id: {result2['result']['message_id']}")
        return result2["result"]["message_id"]
    print(f"Telegram errore: {result2}")
    return None

if __name__ == "__main__":
    now = get_now_it()
    print(f"=== PRONOSTICI ARTICOLO — {now.strftime('%d/%m/%Y %H:%M')} ===")

    partite = fetch_partite_oggi()
    print(f"\nPartite selezionate: {len(partite)}")

    if not partite:
        print("Nessuna partita nei campionati top oggi. Stop.")
        exit(0)

    articolo = genera_articolo(partite, now)

    if not articolo:
        print("Gemini non ha risposto. Stop.")
        exit(1)

    print("\n--- ANTEPRIMA ARTICOLO ---")
    print(articolo[:400] + "...")
    print(f"\nLunghezza: {len(articolo)} caratteri")

    print("\nPubblicazione Telegram...")
    pubblica_telegram(articolo)

    print("\n=== DONE ===")
