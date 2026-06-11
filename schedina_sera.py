import requests, os, json
from datetime import datetime, timezone, timedelta

ODDS_API_KEY = os.environ["ODDS_API_KEY"]
BOT_TOKEN    = os.environ["BOT_TOKEN"]
CHAT_ID      = os.environ["CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
SHEET_ID     = os.environ["SHEET_ID"]
GOOGLE_CREDS = os.environ["GOOGLE_CREDS"]

SPORTS = [
    "soccer_fifa_world_cup", "soccer_italy_serie_a", "soccer_epl",
    "soccer_spain_la_liga", "soccer_germany_bundesliga", "soccer_france_ligue_one",
]

BOOKMAKER_ROTATION = {
    0: ("Lottomatica", "https://media.lottomaticapartners.it/redirect.aspx?pid=8019&bid=1508"),
    1: ("Planetwin",   "https://betly.co/2f70557951"),
    2: ("Lottomatica", "https://media.lottomaticapartners.it/redirect.aspx?pid=8019&bid=1508"),
    3: ("Planetwin",   "https://betly.co/2f70557951"),
    4: ("Lottomatica", "https://media.lottomaticapartners.it/redirect.aspx?pid=8019&bid=1508"),
    5: ("Planetwin",   "https://betly.co/2f70557951"),
    6: ("Lottomatica", "https://media.lottomaticapartners.it/redirect.aspx?pid=8019&bid=1508"),
}

def get_today_it():
    return datetime.now(timezone(timedelta(hours=2)))

def is_today(dt_str):
    it = get_today_it()
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=2)))
        return dt.date() == it.date()
    except:
        return False

def fetch_pick_sera():
    candidates = []
    for sport in SPORTS:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        r = requests.get(url, params={
            "apiKey": ODDS_API_KEY, "regions": "eu",
            "markets": "h2h", "oddsFormat": "decimal", "dateFormat": "iso"
        }, timeout=20)
        if r.status_code != 200:
            continue
        for game in r.json():
            if not is_today(game.get("commence_time", "")):
                continue
            for bk in game.get("bookmakers", []):
                for mkt in bk.get("markets", []):
                    if mkt["key"] != "h2h":
                        continue
                    home = game["home_team"]
                    away = game["away_team"]
                    time_it = datetime.fromisoformat(
                        game["commence_time"].replace("Z", "+00:00")
                    ).astimezone(timezone(timedelta(hours=2))).strftime("%H:%M")
                    for o in mkt["outcomes"]:
                        odd = o["price"]
                        if 2.5 <= odd <= 6.0:
                            sign = "1" if o["name"] == home else ("2" if o["name"] == away else "X")
                            candidates.append({
                                "home": home, "away": away,
                                "competition": sport.replace("soccer_","").replace("_"," ").title(),
                                "sport_key": sport, "time": time_it,
                                "sign": sign, "odd": odd,
                                "commence_time": game["commence_time"]
                            })
                    break
                break
        if candidates:
            break
    if not candidates:
        return None
    candidates.sort(key=lambda x: x["odd"], reverse=True)
    pick = candidates[0]
    return {"picks": [pick], "total_odd": pick["odd"], "vincita": round(pick["odd"]*10,2), "signs_string": pick["sign"]}

def genera_immagine_sera(data):
    p = data["picks"][0]
    labels = {"1": "VINCE CASA", "X": "PAREGGIO", "2": "VINCE OSPITE"}
    prompt = f"""Football betting poster square 1:1. Dark cinematic background, green pitch, stadium lights.
Single large panel: '{p['home']} vs {p['away']}' - '{p['time']}'. Huge gold badge: '{p['sign']}'.
Label: '{labels.get(p['sign'],'')} @{p['odd']}'. TOP: '{p['competition'].upper()}' with fire and trophy.
BOTTOM: 'QUOTA {data['total_odd']}x | €10 → €{data['vincita']}'. Ultra professional, cinematic, 4K."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp-image-generation:generateContent?key={GEMINI_API_KEY}"
    r = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}, timeout=120)
    if r.status_code != 200:
        return None
    for part in r.json()["candidates"][0]["content"]["parts"]:
        if part.get("inlineData"):
            import base64
            img_bytes = base64.b64decode(part["inlineData"]["data"])
            with open("/tmp/poster_sera.jpg", "wb") as f:
                f.write(img_bytes)
            return "/tmp/poster_sera.jpg"
    return None

def pubblica_telegram(data, img_path, bookmaker, link):
    p = data["picks"][0]
    caption = f"""🎯 PICK DELLA SERA 🎯

🏆 *{p['competition']}*

✅ {p['home']} *{p['sign']}* {p['away']} @{p['odd']}

🎰 *QUOTA {data['total_odd']}x*
💰 Puntata €10 — *VINCITA POTENZIALE €{data['vincita']}*

➡️ [GIOCA SU {bookmaker}]({link})

🎁 Bonus di benvenuto
⚠️ Solo per maggiorenni – gioca responsabilmente"""
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
        print(f"Telegram OK — message_id: {result['result']['message_id']}")
        return result["result"]["message_id"]
    print(f"Telegram ERROR: {result}")
    return None

def salva_sheet(data, msg_id, bookmaker):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_info(
        json.loads(GOOGLE_CREDS), scopes=["https://www.googleapis.com/auth/spreadsheets"])
    service = build("sheets", "v4", credentials=creds)
    it = get_today_it()
    p = data["picks"][0]
    row = [it.strftime("%d/%m/%Y"), "sera", bookmaker, p["competition"],
           f"{p['home']}-{p['away']}-{p['sign']}-{p['odd']}", "","","","",
           data["total_odd"], 10, data["vincita"], msg_id or "",
           p["sport_key"], "PENDING", p["time"], ""]
    service.spreadsheets().values().append(
        spreadsheetId=SHEET_ID, range="Foglio1!A:Q",
        valueInputOption="USER_ENTERED", body={"values": [row]}).execute()
    print("Sheet aggiornato.")

if __name__ == "__main__":
    print("=== SCHEDINA SERA ===")
    it = get_today_it()
    bookmaker, link = BOOKMAKER_ROTATION[it.weekday()]
    print(f"Bookmaker: {bookmaker}")
    data = fetch_pick_sera()
    if not data:
        print("Nessun pick disponibile stasera.")
        exit(0)
    print(f"Pick: {data['picks'][0]['home']} {data['signs_string']} {data['picks'][0]['away']} @{data['total_odd']}")
    img = genera_immagine_sera(data)
    msg_id = pubblica_telegram(data, img, bookmaker, link)
    try:
        salva_sheet(data, msg_id, bookmaker)
    except Exception as e:
        print(f"Sheet error: {e}")
    print("=== DONE ===")
