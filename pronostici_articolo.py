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

TOP_LEAGUES = [1, 2, 3, 135, 39, 140, 78, 61]

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

def fetch_partite_oggi():
    headers = {"x-apisports-key": APIFOOTBALL_KEY}
    now_it = get_now_it()
    date_str = now_it.strftime("%Y-%m-%d")

    r = requests.get("https://v3.football.api-sports.io/fixtures",
        headers=headers,
        params={"date": date_str, "timezone": "Europe/Rome"})

    if r.status_code != 200:
        print(f"API-Football errore: {r.status_code}")
        return []

    all_fixtures = r.json().get("response", [])
    partite = []

    for f in all_fixtures:
        if f["league"]["id"] not in TOP_LEAGUES:
            continue
        if f["fixture"]["status"]["short"] not in ["NS", "TBD"]:
            continue

        fixture_id = f["fixture"]["id"]
        home = f["teams"]["home"]["name"]
        away = f["teams"]["away"]["name"]
        orario = f["fixture"]["date"][11:16]
        league_name = f["league"]["name"]

        # Fetch quote
        odds_1 = odds_x = odds_2 = None
        for bk_id in [8, 6, 1]:
            ro = requests.get("https://v3.football.api-sports.io/odds",
                headers=headers,
                params={"fixture": fixture_id, "bookmaker": bk_id})
            odds_data = ro.json().get("response", [])
            if odds_data:
                for bk in odds_data[0].get("bookmakers", []):
                    for bet in bk.get("bets", []):
                        if bet["name"] == "Match Winner":
                            for v in bet["values"]:
                                if v["value"] == "Home": odds_1 = v["odd"]
                                elif v["value"] == "Draw": odds_x = v["odd"]
                                elif v["value"] == "Away": odds_2 = v["odd"]
                            break
                if odds_1:
                    break
            time.sleep(0.3)

        partite.append({
            "id": fixture_id,
            "home": home,
            "away": away,
            "orario": orario,
            "league": league_name,
            "league_id": f["league"]["id"],
            "odds_1": odds_1 or "N/D",
            "odds_x": odds_x or "N/D",
            "odds_2": odds_2 or "N/D",
        })
        print(f"  {orario} {home} vs {away} [{league_name}] 1={odds_1} X={odds_x} 2={odds_2}")

    partite.sort(key=lambda x: (TOP_LEAGUES.index(x["league_id"]) if x["league_id"] in TOP_LEAGUES else 99, x["orario"]))
    return partite

def genera_articolo(partite, now_it):
    partite_testo = ""
    for i, p in enumerate(partite, 1):
        partite_testo += f"{i}. {p['home']} vs {p['away']} ({p['league']}) ore {p['orario']}\n"
        partite_testo += f"   Quote: 1={p['odds_1']}  X={p['odds_x']}  2={p['odds_2']}\n\n"

    prompt = f"""Sei un analista calcistico professionista italiano che scrive per il canale Telegram SuperPronostico.
Oggi e {now_it.strftime('%A %d %B %Y')}.

Scrivi un post Telegram professionale con l'analisi delle partite di oggi.
Il tono deve essere autorevole, appassionato, da vero esperto di calcio.

PARTITE DI OGGI:
{partite_testo}

STRUTTURA DEL POST:
1. Intestazione con emoji, data e titolo tipo "LE ANALISI DI OGGI"
2. Per ogni partita:
   - *Home vs Away* in grassetto con emoji ⚽
   - 2-3 righe di analisi: contesto, forma, fattori chiave
   - Pronostico motivato in grassetto es: *Pronostico: Vittoria Canada @1.85*
   - Quote: 1=[X] X=[X] 2=[X]
   - Separatore ---
3. Chiusura con invito a seguire il canale e disclaimer

REGOLE:
- Usa *testo* per grassetto Telegram
- Emoji vivaci ma professionali
- Massimo 3800 caratteri totali
- Scrivi in italiano
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

    print("\nFetch partite di oggi...")
    partite = fetch_partite_oggi()
    print(f"Partite trovate: {len(partite)}")

    if not partite:
        print("Nessuna partita nei campionati top oggi. Stop.")
        exit(0)

    print("\nGenerazione articolo con Gemini...")
    articolo = genera_articolo(partite, now)

    if not articolo:
        print("Gemini non ha risposto. Stop.")
        exit(1)

    print("\n--- ARTICOLO ---")
    print(articolo[:300] + "...")

    print("\nPubblicazione Telegram...")
    pubblica_telegram(articolo)

    print("\n=== DONE ===")
