import requests, os, json
from datetime import datetime, timezone, timedelta

BOT_TOKEN    = os.environ["BOT_TOKEN"]
CHAT_ID      = os.environ["CHAT_ID"]
ODDS_API_KEY = os.environ["ODDS_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
SHEET_ID     = os.environ["SHEET_ID"]
GOOGLE_CREDS = os.environ["GOOGLE_CREDS"]

BOOKMAKER_LINKS = {
    "Sisal":       "https://ads.sisal.it/promoRedirect?key=ej0xMzUyNDE2MyZsPTEzNTQ1NTEyJnA9MjM5NzY%3D",
    "Lottomatica": "https://media.lottomaticapartners.it/redirect.aspx?pid=8019&bid=1508",
    "Goldbet":     "https://betly.co/952194909",
    "Planetwin":   "https://betly.co/2f70557951",
}

def get_sheet_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_info(
        json.loads(GOOGLE_CREDS), scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return build("sheets", "v4", credentials=creds)

def leggi_pending():
    svc = get_sheet_service()
    result = svc.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range="Foglio1!A:Q").execute()
    rows = result.get("values", [])
    if not rows:
        return []
    headers = rows[0]
    pending = []
    for i, row in enumerate(rows[1:], start=2):
        while len(row) < len(headers):
            row.append("")
        d = dict(zip(headers, row))
        if d.get("Stato") == "PENDING":
            d["_row_num"] = i
            pending.append(d)
    return pending

def parse_picks(row):
    picks = []
    for col in ["Pick 1", "Pick 2", "Pick 3", "Pick 4", "Pick 5"]:
        val = row.get(col, "").strip()
        if not val:
            continue
        parts = val.split("-")
        if len(parts) >= 4:
            picks.append({"home": parts[0], "away": parts[1], "sign": parts[2], "odd": float(parts[3])})
    return picks

def fetch_scores(sport_key):
    r = requests.get(
        f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/",
        params={"apiKey": ODDS_API_KEY, "daysFrom": 2, "dateFormat": "iso"}, timeout=20)
    if r.status_code != 200:
        return []
    return r.json()

def valuta_pick(scores_data, pick):
    for game in scores_data:
        home = game.get("home_team", "")
        away = game.get("away_team", "")
        if pick["home"].lower() not in home.lower() and pick["away"].lower() not in away.lower():
            continue
        if not game.get("completed"):
            return None
        scores = game.get("scores") or []
        score_map = {s["name"]: int(s["score"]) for s in scores if str(s.get("score","")).isdigit()}
        hs = score_map.get(home, 0)
        as_ = score_map.get(away, 0)
        if pick["sign"] == "1":
            return hs > as_
        elif pick["sign"] == "X":
            return hs == as_
        elif pick["sign"] == "2":
            return as_ > hs
    return None

def genera_immagine_vittoria(total_odd, vincita):
    prompt = f"Celebration victory poster square 1:1. Gold confetti, fireworks, trophy, green and gold colors. Bold: 'SCHEDINA VINCENTE!' top. 'QUOTA {total_odd}x CENTRATA!' center. 'PUNTATA €10 → VINCITA €{vincita}' bottom. Ultra professional, cinematic, 4K."
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp-image-generation:generateContent?key={GEMINI_API_KEY}"
    r = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}, timeout=120)
    if r.status_code != 200:
        return None
    for part in r.json()["candidates"][0]["content"]["parts"]:
        if part.get("inlineData"):
            import base64
            img_bytes = base64.b64decode(part["inlineData"]["data"])
            with open("/tmp/vittoria.jpg", "wb") as f:
                f.write(img_bytes)
            return "/tmp/vittoria.jpg"
    return None

def pubblica_vittoria(row, picks, img_path):
    bookmaker = row.get("Bookmaker", "Sisal")
    link = BOOKMAKER_LINKS.get(bookmaker, BOOKMAKER_LINKS["Sisal"])
    total = row.get("Quota Totale", "?")
    vincita = row.get("Vincita Potenziale", "?")
    lines = "\n".join(f"✅ {p['home']} *{p['sign']}* {p['away']} — VINTO @{p['odd']}" for p in picks)
    caption = f"""🏆🏆 SCHEDINA VINCENTE! 🏆🏆

{lines}

🎰 *QUOTA {total}x CENTRATA!*
💰 €10 puntati → *€{vincita} VINTI!*

🔥 Chi ha giocato con noi ha vinto!
➡️ Domani ci riproviamo — seguici!

[{bookmaker}]({link})
⚠️ Solo per maggiorenni – gioca responsabilmente"""
    if img_path and os.path.exists(img_path):
        with open(img_path, "rb") as f:
            r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "Markdown"},
                files={"photo": ("vittoria.jpg", f, "image/jpeg")})
    else:
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": caption, "parse_mode": "Markdown"})
    print(f"Post vittoria pubblicato: {r.json().get('ok')}")

def aggiorna_sheet(row_num, stato, note):
    svc = get_sheet_service()
    svc.spreadsheets().values().update(
        spreadsheetId=SHEET_ID, range=f"Foglio1!O{row_num}:Q{row_num}",
        valueInputOption="USER_ENTERED", body={"values": [[stato, "", note]]}).execute()

if __name__ == "__main__":
    print("=== CONTROLLA RISULTATI ===")
    pending = leggi_pending()
    print(f"Schedine PENDING: {len(pending)}")
    for row in pending:
        picks = parse_picks(row)
        if not picks:
            continue
        sport_key = row.get("Sport Key", "soccer_fifa_world_cup")
        scores_data = fetch_scores(sport_key)
        results = [valuta_pick(scores_data, p) for p in picks]
        if None in results:
            print(f"Riga {row['_row_num']}: partite non ancora finite, skip.")
            continue
        vinta = all(results)
        if vinta:
            print(f"Riga {row['_row_num']}: VINTA!")
            img = genera_immagine_vittoria(row.get("Quota Totale","?"), row.get("Vincita Potenziale","?"))
            pubblica_vittoria(row, picks, img)
            aggiorna_sheet(row["_row_num"], "VINTA", f"Quota {row.get('Quota Totale')}x centrata")
        else:
            persi = [picks[i] for i,r in enumerate(results) if not r]
            note = "Pick persi: " + ", ".join(f"{p['home']} {p['sign']} {p['away']}" for p in persi)
            print(f"Riga {row['_row_num']}: PERSA. {note}")
            aggiorna_sheet(row["_row_num"], "PERSA", note)
    print("=== DONE ===")
