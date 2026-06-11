import requests
import os
import json
import base64
import time
from datetime import datetime, timezone, timedelta
import sys

# ─── CONFIG ──────────────────────────────────────────────────
ODDS_API_KEY   = os.environ["ODDS_API_KEY"]
BOT_TOKEN      = os.environ["BOT_TOKEN"]
CHAT_ID        = os.environ["CHAT_ID"]
# Raccoglie tutte le API key Gemini disponibili (rotazione in caso di 429)
GEMINI_API_KEYS = [
    os.environ.get("GEMINI_API_KEY", ""),
    os.environ.get("GEMINI_API_KEY_2", ""),
    os.environ.get("GEMINI_API_KEY_3", ""),
    os.environ.get("GEMINI_API_KEY_4", ""),
    os.environ.get("GEMINI_API_KEY_5", ""),
]
GEMINI_API_KEYS = [k for k in GEMINI_API_KEYS if k]  # rimuove key vuote
GEMINI_API_KEY = GEMINI_API_KEYS[0]  # backward compat per genera_immagine
SHEET_ID       = os.environ["SHEET_ID"]
GOOGLE_CREDS   = os.environ["GOOGLE_CREDS"]

FASCIA = sys.argv[1] if len(sys.argv) > 1 else "mattina"

FASCE = {
    "mattina": {"pubblica_dalle": 11, "pubblica_alle": 13},
    "sera":    {"pubblica_dalle": 16, "pubblica_alle": 18},
}

BOOKMAKER_ROTATION = {
    (0, "mattina"): ("Sisal",       "https://ads.sisal.it/promoRedirect?key=ej0xMzUyNDE2MyZsPTEzNTQ1NTEyJnA9MjM5NzY%3D"),
    (0, "sera"):    ("Lottomatica", "https://media.lottomaticapartners.it/redirect.aspx?pid=8019&bid=1508"),
    (1, "mattina"): ("Goldbet",     "https://betly.co/952194909"),
    (1, "sera"):    ("Planetwin",   "https://betly.co/2f70557951"),
    (2, "mattina"): ("Sisal",       "https://ads.sisal.it/promoRedirect?key=ej0xMzUyNDE2MyZsPTEzNTQ1NTEyJnA9MjM5NzY%3D"),
    (2, "sera"):    ("Lottomatica", "https://media.lottomaticapartners.it/redirect.aspx?pid=8019&bid=1508"),
    (3, "mattina"): ("Goldbet",     "https://betly.co/952194909"),
    (3, "sera"):    ("Planetwin",   "https://betly.co/2f70557951"),
    (4, "mattina"): ("Sisal",       "https://ads.sisal.it/promoRedirect?key=ej0xMzUyNDE2MyZsPTEzNTQ1NTEyJnA9MjM5NzY%3D"),
    (4, "sera"):    ("Lottomatica", "https://media.lottomaticapartners.it/redirect.aspx?pid=8019&bid=1508"),
    (5, "mattina"): ("Goldbet",     "https://betly.co/952194909"),
    (5, "sera"):    ("Planetwin",   "https://betly.co/2f70557951"),
    (6, "mattina"): ("Sisal",       "https://ads.sisal.it/promoRedirect?key=ej0xMzUyNDE2MyZsPTEzNTQ1NTEyJnA9MjM5NzY%3D"),
    (6, "sera"):    ("Lottomatica", "https://media.lottomaticapartners.it/redirect.aspx?pid=8019&bid=1508"),
}

SPORTS = [
    ("soccer_fifa_world_cup",       "FIFA World Cup 2026",  10),
    ("soccer_uefa_champs_league",   "Champions League",      9),
    ("soccer_uefa_europa_league",   "Europa League",         8),
    ("soccer_italy_serie_a",        "Serie A",               7),
    ("soccer_epl",                  "Premier League",        7),
    ("soccer_spain_la_liga",        "La Liga",               7),
    ("soccer_germany_bundesliga",   "Bundesliga",            7),
    ("soccer_france_ligue_one",     "Ligue 1",               6),
]

def get_now_it():
    return datetime.now(timezone(timedelta(hours=2)))

def is_today(dt_str):
    it = get_now_it()
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=2)))
        return dt.date() == it.date()
    except:
        return False

def format_time_it(dt_str):
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=2)))
        return dt.strftime("%H:%M")
    except:
        return "??"

def fetch_all_games():
    all_games = []
    for sport_key, sport_name, priority in SPORTS:
        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
        r = requests.get(url, params={
            "apiKey": ODDS_API_KEY, "regions": "eu",
            "markets": "h2h", "oddsFormat": "decimal", "dateFormat": "iso"
        }, timeout=20)
        if r.status_code != 200:
            print(f"  {sport_name}: HTTP {r.status_code}")
            continue
        games = r.json()
        today_games = [g for g in games if is_today(g.get("commence_time", ""))]
        print(f"  {sport_name}: {len(today_games)} partite oggi")
        for game in today_games:
            odds_1 = odds_x = odds_2 = None
            for bk in game.get("bookmakers", []):
                for mkt in bk.get("markets", []):
                    if mkt["key"] != "h2h":
                        continue
                    for o in mkt["outcomes"]:
                        if o["name"] == game["home_team"]:
                            odds_1 = round(o["price"], 2)
                        elif o["name"] == game["away_team"]:
                            odds_2 = round(o["price"], 2)
                        else:
                            odds_x = round(o["price"], 2)
                    break
                if odds_1:
                    break
            if not odds_1:
                continue
            all_games.append({
                "home": game["home_team"],
                "away": game["away_team"],
                "competition": sport_name,
                "sport_key": sport_key,
                "priority": priority,
                "time_it": format_time_it(game["commence_time"]),
                "commence_time": game["commence_time"],
                "odds": {"1": odds_1, "X": odds_x, "2": odds_2}
            })
    return all_games

def gemini_decide(games, fascia):
    fascia_info = FASCE[fascia]
    now_it = get_now_it()
    games_text = ""
    for i, g in enumerate(games, 1):
        o = g["odds"]
        games_text += f"{i}. {g['home']} vs {g['away']} ({g['competition']}) ore {g['time_it']}\n"
        games_text += f"   Quote: 1={o['1']} X={o['X']} 2={o['2']} | Priorita campionato: {g['priority']}/10\n\n"
    if not games_text:
        games_text = "Nessuna partita disponibile oggi."

    prompt = f"""Sei il cervello di un tipster calcistico professionale italiano.
Gestisci il canale Telegram SuperPronostico e devi decidere la schedina per la fascia {fascia.upper()}.

ORA ATTUALE (Italia): {now_it.strftime("%H:%M")} del {now_it.strftime("%d/%m/%Y")}
FASCIA: {fascia} (pubblica tra le {fascia_info['pubblica_dalle']}:00 e le {fascia_info['pubblica_alle']}:00 ora italiana)

PARTITE DISPONIBILI OGGI:
{games_text}

Il tuo compito:
1. Valuta se c'e materiale interessante per una schedina di qualita
2. Scegli il TIPO ottimale: combo (3-5 picks, quota 8x-50x) oppure singola/doppia (quota 2.5x-6x)
3. Seleziona i picks migliori considerando: importanza campionato, orario partita (preferisci partite che iniziano DOPO la pubblicazione), valore delle quote
4. Per ogni pick scegli il segno: 1 (vince casa), X (pareggio), 2 (vince ospite)
5. Se non ci sono partite interessanti o di qualita sufficiente, di' di NON pubblicare

REGOLE:
- Puntata fissa: 10 euro
- Per combo: quota totale tra 8x e 50x
- Per singola/doppia: quota tra 2.5x e 6x per pick
- Preferisci campionati ad alta priorita (World Cup > CL > top 5 europei)
- Preferisci partite che iniziano almeno 1 ora dopo la pubblicazione
- Se ci sono meno di 2 partite valide oggi, non pubblicare

Rispondi SOLO con un JSON valido, senza markdown, senza backtick, senza testo aggiuntivo:

{{"pubblica": true, "motivo_no": null, "tipo": "combo", "picks": [{{"home": "squadra", "away": "squadra", "competition": "nome", "sport_key": "key", "time": "HH:MM", "sign": "1", "odd": 1.5}}], "total_odd": 8.5, "vincita": 85.0, "signs_string": "1 - X - 2", "ragionamento": "spiegazione"}}"""

    # Modelli in ordine di fallback (tutti disponibili su Gemini API gratuita)
    models = [
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.5-flash",
        "gemini-flash-latest",
        "gemini-flash-lite-latest",
        "gemini-pro-latest",
        "gemini-2.5-flash-lite",
    ]
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1000}}

    # Ruota su ogni combinazione key+modello finché una funziona
    for api_key in GEMINI_API_KEYS:
        key_short = api_key[:12] + "..."
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            print(f"Provo {model} con key {key_short}")
            try:
                r = requests.post(url, json=body, timeout=60)
                if r.status_code == 200:
                    text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                    text = text.replace("```json", "").replace("```", "").strip()
                    try:
                        decision = json.loads(text)
                        print(f"OK — pubblica={decision.get('pubblica')}")
                        print(f"Ragionamento: {decision.get('ragionamento', '')}")
                        return decision
                    except json.JSONDecodeError as e:
                        print(f"Errore JSON: {e} — provo prossimo modello")
                        break
                elif r.status_code == 429:
                    print(f"429 rate limit su {model}/{key_short} — provo prossimo")
                    continue
                elif r.status_code == 404:
                    print(f"404 modello non trovato: {model} — provo prossimo")
                    continue
                else:
                    print(f"Errore {r.status_code} su {model}/{key_short} — provo prossimo")
                    continue
            except Exception as e:
                print(f"Eccezione {model}/{key_short}: {e}")
                continue

    print("Tutte le key e modelli Gemini hanno fallito.")
    return None
def genera_immagine(decision):
    picks = decision["picks"]
    tipo = decision["tipo"]
    total = decision["total_odd"]
    vincita = decision["vincita"]
    signs = decision["signs_string"]
    competition = picks[0]["competition"]
    labels = {"1": "VINCE CASA", "X": "PAREGGIO", "2": "VINCE OSPITE"}
    n = len(picks)
    if n == 1:
        panels = f"Single large panel center: '{picks[0]['home']} vs {picks[0]['away']}' ore {picks[0]['time']}. Huge gold badge: '{picks[0]['sign']}'. Label: '{labels.get(picks[0]['sign'],'')} @{picks[0]['odd']}'"
    else:
        pos_map = {2: ["LEFT", "RIGHT"], 3: ["LEFT", "CENTER", "RIGHT"], 4: ["TOP-LEFT", "TOP-RIGHT", "BOTTOM-LEFT", "BOTTOM-RIGHT"], 5: ["TOP-LEFT", "TOP-CENTER", "TOP-RIGHT", "BOTTOM-LEFT", "BOTTOM-RIGHT"]}
        positions = pos_map.get(n, [f"PANEL {i+1}" for i in range(n)])
        panels = " ".join([f"{positions[i]} PANEL: '{p['home']} vs {p['away']}' ore {p['time']}. Badge: '{p['sign']}'. Label: '{labels.get(p['sign'],'')} @{p['odd']}'." for i, p in enumerate(picks)])
    bottom = f"COMBO {signs} | QUOTA {total}x | PUNTATA 10 EUR VINCITA {vincita} EUR" if tipo == "combo" else f"QUOTA {total}x | PUNTATA 10 EUR VINCITA {vincita} EUR"
    prompt = f"Professional football sports betting match poster, square 1:1 format. Dark cinematic background, glowing green pitch, stadium lights, golden sparks. {n} match panel(s): {panels} TOP: Bold gold '{competition.upper()}' with fire and trophy. BOTTOM: Dark green, bold gold '{bottom}'. Ultra professional, cinematic, photorealistic, 4K."
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp-image-generation:generateContent?key={GEMINI_API_KEY}"
    r = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}, timeout=180)
    if r.status_code != 200:
        return None
    for part in r.json()["candidates"][0]["content"]["parts"]:
        if part.get("inlineData"):
            img_bytes = base64.b64decode(part["inlineData"]["data"])
            with open("/tmp/poster.jpg", "wb") as f:
                f.write(img_bytes)
            return "/tmp/poster.jpg"
    return None

def pubblica_telegram(decision, img_path, bookmaker, link):
    picks = decision["picks"]
    total = decision["total_odd"]
    vincita = decision["vincita"]
    signs = decision["signs_string"]
    tipo = decision["tipo"]
    competition = picks[0]["competition"]
    lines = "\n".join(f"✅ {p['home']} *{p['sign']}* {p['away']} @{p['odd']}" for p in picks)
    quota_line = f"🎰 *COMBO {signs} | QUOTA {total}x*" if tipo == "combo" else f"🎰 *QUOTA {total}x*"
    caption = f"""🔥🔥 HAI VISTO CHE SCHEDINA? 🔥🔥

🏆 *{competition}*

{lines}

{quota_line}
💰 Puntata €10 — *VINCITA POTENZIALE €{vincita}*

Se non sei ancora su [{bookmaker}]({link}), questa è la schedina perfetta 👇
➡️ [REGISTRATI ORA SU {bookmaker}]({link})

🎁 Bonus di benvenuto per i nuovi utenti
⚠️ Solo per maggiorenni – gioca responsabilmente"""
    if len(caption) > 1024:
        caption = caption[:1020] + "..."
    if img_path and os.path.exists(img_path):
        with open(img_path, "rb") as f:
            r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "Markdown"},
                files={"photo": ("poster.jpg", f, "image/jpeg")})
    else:
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": caption, "parse_mode": "Markdown"})
    result = r.json()
    if result.get("ok"):
        msg_id = result["result"]["message_id"]
        print(f"Telegram OK — message_id: {msg_id}")
        return msg_id
    print(f"Telegram ERROR: {result}")
    return None

def salva_sheet(decision, msg_id, bookmaker, fascia):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_info(
        json.loads(GOOGLE_CREDS), scopes=["https://www.googleapis.com/auth/spreadsheets"])
    service = build("sheets", "v4", credentials=creds)
    now = get_now_it()
    picks = decision["picks"]
    pick_cols = [""] * 5
    for i, p in enumerate(picks[:5]):
        pick_cols[i] = f"{p['home']}-{p['away']}-{p['sign']}-{p['odd']}"
    row = [now.strftime("%d/%m/%Y"), fascia, bookmaker, picks[0]["competition"],
           pick_cols[0], pick_cols[1], pick_cols[2], pick_cols[3], pick_cols[4],
           decision["total_odd"], 10, decision["vincita"], msg_id or "",
           picks[0]["sport_key"], "PENDING", picks[-1]["time"], decision.get("ragionamento", "")]
    service.spreadsheets().values().append(
        spreadsheetId=SHEET_ID, range="Foglio1!A:Q",
        valueInputOption="USER_ENTERED", body={"values": [row]}).execute()
    print("Sheet aggiornato.")

if __name__ == "__main__":
    now = get_now_it()
    print(f"=== TIPSTER GEMINI — {FASCIA.upper()} ===")
    print(f"Ora IT: {now.strftime('%H:%M')} | {now.strftime('%A %d/%m/%Y')}")
    bookmaker, link = BOOKMAKER_ROTATION.get((now.weekday(), FASCIA), ("Sisal", "https://ads.sisal.it/promoRedirect?key=ej0xMzUyNDE2MyZsPTEzNTQ1NTEyJnA9MjM5NzY%3D"))
    print(f"Bookmaker: {bookmaker}")
    print("\nFetch partite di oggi...")
    games = fetch_all_games()
    print(f"Totale partite: {len(games)}")
    if not games:
        print("Nessuna partita oggi. Stop.")
        sys.exit(0)
    print("\nGemini sta decidendo...")
    decision = gemini_decide(games, FASCIA)
    if not decision:
        print("Errore Gemini. Stop.")
        sys.exit(1)
    if not decision.get("pubblica"):
        print(f"Gemini: non pubblico. Motivo: {decision.get('motivo_no', 'non specificato')}")
        sys.exit(0)
    print("\nPicks selezionati da Gemini:")
    for p in decision["picks"]:
        print(f"  {p['home']} {p['sign']} {p['away']} @{p['odd']} ({p['competition']}) ore {p['time']}")
    print(f"Tipo: {decision['tipo']} | Quota: {decision['total_odd']}x | Vincita: €{decision['vincita']}")
    print("\nGenerazione immagine...")
    img = genera_immagine(decision)
    print("\nPubblicazione Telegram...")
    msg_id = pubblica_telegram(decision, img, bookmaker, link)
    if msg_id:
        try:
            salva_sheet(decision, msg_id, bookmaker, FASCIA)
        except Exception as e:
            print(f"Sheet error: {e}")
    print("\n=== DONE ===")
