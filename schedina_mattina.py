import requests
import json
import os
from datetime import datetime, timezone, timedelta

# ─── CONFIG ──────────────────────────────────────────────────
ODDS_API_KEY    = os.environ["ODDS_API_KEY"]
BOT_TOKEN       = os.environ["BOT_TOKEN"]
CHAT_ID         = os.environ["CHAT_ID"]
GEMINI_API_KEY  = os.environ["GEMINI_API_KEY"]
SHEET_ID        = os.environ["SHEET_ID"]
GOOGLE_CREDS    = os.environ["GOOGLE_CREDS"]

SPORTS = [
    "soccer_fifa_world_cup",
    "soccer_italy_serie_a",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_germany_bundesliga",
    "soccer_france_ligue_one",
]

BOOKMAKER_ROTATION = {
    0: ("Sisal",       "https://ads.sisal.it/promoRedirect?key=ej0xMzUyNDE2MyZsPTEzNTQ1NTEyJnA9MjM5NzY%3D"),
    1: ("Goldbet",     "https://betly.co/952194909"),
    2: ("Sisal",       "https://ads.sisal.it/promoRedirect?key=ej0xMzUyNDE2MyZsPTEzNTQ1NTEyJnA9MjM5NzY%3D"),
    3: ("Goldbet",     "https://betly.co/952194909"),
    4: ("Sisal",       "https://ads.sisal.it/promoRedirect?key=ej0xMzUyNDE2MyZsPTEzNTQ1NTEyJnA9MjM5NzY%3D"),
    5: ("Goldbet",     "https://betly.co/952194909"),
    6: ("Sisal",       "https://ads.sisal.it/promoRedirect?key=ej0xMzUyNDE2MyZsPTEzNTQ1NTEyJnA9MjM5NzY%3D"),
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

def fetch_picks():
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
                    outcomes = mkt["outcomes"]
                    home = game["home_team"]
                    away = game["away_team"]
                    time_it = datetime.fromisoformat(
                        game["commence_time"].replace("Z", "+00:00")
                    ).astimezone(timezone(timedelta(hours=2))).strftime("%H:%M")
                    for o in outcomes:
                        odd = o["price"]
                        if odd < 1.4 or odd > 7.0:
                            continue
                        if o["name"] == home:
                            sign = "1"
                        elif o["name"] == away:
                            sign = "2"
                        else:
                            sign = "X"
                        candidates.append({
                            "home": home, "away": away,
                            "competition": sport.replace("soccer_", "").replace("_", " ").title(),
                            "sport_key": sport,
                            "time": time_it,
                            "sign": sign, "odd": odd,
                            "commence_time": game["commence_time"]
                        })
                    break
                break
        if len(candidates) >= 10:
            break

    if len(candidates) < 3:
        print("Nessuna partita sufficiente oggi.")
        return None

    candidates.sort(key=lambda x: x["odd"], reverse=True)
    best = None
    for i in range(len(candidates)):
        for j in range(i+1, len(candidates)):
            for k in range(j+1, len(candidates)):
                combo = [candidates[i], candidates[j], candidates[k]]
                games = [f"{c['home']}{c['away']}" for c in combo]
                if len(set(games)) < 3:
                    continue
                total = round(combo[0]["odd"] * combo[1]["odd"] * combo[2]["odd"], 2)
                if 8.0 <= total <= 50.0:
                    best = {"picks": combo, "total_odd": total}
                    break
            if best: break
        if best: break

    if not best:
        seen = set()
        picks = []
        for c in candidates:
            key = f"{c['home']}{c['away']}"
            if key not in seen:
                picks.append(c)
                seen.add(key)
            if len(picks) == 3:
                break
        total = round(picks[0]["odd"] * picks[1]["odd"] * picks[2]["odd"], 2)
        best = {"picks": picks, "total_odd": total}

    best["vincita"] = round(best["total_odd"] * 10, 2)
    best["signs_string"] = " - ".join(p["sign"] for p in best["picks"])
    return best

def genera_immagine(data):
    picks = data["picks"]
    labels = {"1": "VINCE CASA", "X": "PAREGGIO", "2": "VINCE OSPITE"}
    panels = ""
    for i, p in enumerate(picks):
        pos = ["LEFT", "CENTER", "RIGHT"][i] if i < 3 else f"PANEL {i+1}"
        border = " (highlighted gold border)" if i == 1 else ""
        panels += f"\n{pos} PANEL{border}: '{p['home']} vs {p['away']}' - '{p['time']}'. Badge: '{p['sign']}'. Label: '{labels.get(p['sign'], '')} @{p['odd']}'"

    signs = data["signs_string"]
    total = data["total_odd"]
    vincita = data["vincita"]
    competition = picks[0]["competition"]

    prompt = f"""Professional football sports betting match poster, square 1:1 format.
Dark cinematic background, glowing green pitch, stadium lights, golden sparks.
{len(picks)} match panels side by side with golden dividing lines:{panels}
TOP: Bold gold '{competition.upper()}' with fire and trophy.
BOTTOM: Dark green, bold gold 'COMBO {signs} | QUOTA {total}x | PUNTATA €10 → VINCITA €{vincita}'.
Ultra professional, cinematic, photorealistic players, 4K."""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp-image-generation:generateContent?key={GEMINI_API_KEY}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}
    }
    r = requests.post(url, json=body, timeout=120)
    if r.status_code != 200:
        print(f"Gemini error: {r.status_code}")
        return None
    for part in r.json()["candidates"][0]["content"]["parts"]:
        if part.get("inlineData"):
            import base64
            img_bytes = base64.b64decode(part["inlineData"]["data"])
            with open("/tmp/poster.jpg", "wb") as f:
                f.write(img_bytes)
            return "/tmp/poster.jpg"
    return None

def pubblica_telegram(data, img_path, bookmaker, link):
    picks = data["picks"]
    total = data["total_odd"]
    vincita = data["vincita"]
    signs = data["signs_string"]
    competition = picks[0]["competition"]
    lines = "\n".join(f"✅ {p['home']} *{p['sign']}* {p['away']} @{p['odd']}" for p in picks)
    caption = f"""🔥🔥 HAI VISTO CHE SCHEDINA? 🔥🔥

🏆 *{competition}*

{lines}

🎰 *COMBO {signs} | QUOTA {total}x*
💰 Puntata €10 — *VINCITA POTENZIALE €{vincita}*

Se non sei ancora su [{bookmaker}]({link}), questa è la schedina perfetta 👇
➡️ [REGISTRATI ORA SU {bookmaker}]({link})

🎁 Bonus di benvenuto per i nuovi utenti
⚠️ Solo per maggiorenni – gioca responsabilmente"""

    if len(caption) > 1024:
        caption = caption[:1020] + "..."

    if img_path and os.path.exists(img_path):
        with open(img_path, "rb") as f:
            r = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "Markdown"},
                files={"photo": ("poster.jpg", f, "image/jpeg")}
            )
    else:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": caption, "parse_mode": "Markdown"}
        )
    result = r.json()
    if result.get("ok"):
        msg_id = result["result"]["message_id"]
        print(f"Telegram OK — message_id: {msg_id}")
        return msg_id
    print(f"Telegram ERROR: {result}")
    return None

def salva_sheet(data, msg_id, bookmaker):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    import json as jsonlib
    creds = service_account.Credentials.from_service_account_info(
        jsonlib.loads(GOOGLE_CREDS),
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds)
    it = get_today_it()
    picks = data["picks"]
    row = [
        it.strftime("%d/%m/%Y"), "mattina", bookmaker, picks[0]["competition"],
        f"{picks[0]['home']}-{picks[0]['away']}-{picks[0]['sign']}-{picks[0]['odd']}",
        f"{picks[1]['home']}-{picks[1]['away']}-{picks[1]['sign']}-{picks[1]['odd']}",
        f"{picks[2]['home']}-{picks[2]['away']}-{picks[2]['sign']}-{picks[2]['odd']}",
        "", "", data["total_odd"], 10, data["vincita"],
        msg_id or "", picks[0]["sport_key"], "PENDING", picks[-1]["time"], ""
    ]
    service.spreadsheets().values().append(
        spreadsheetId=SHEET_ID, range="Foglio1!A:Q",
        valueInputOption="USER_ENTERED", body={"values": [row]}
    ).execute()
    print("Sheet aggiornato.")

if __name__ == "__main__":
    print("=== SCHEDINA MATTINA ===")
    it = get_today_it()
    bookmaker, link = BOOKMAKER_ROTATION[it.weekday()]
    print(f"Bookmaker: {bookmaker}")
    data = fetch_picks()
    if not data:
        exit(0)
    print(f"Picks: {data['signs_string']} | Quota: {data['total_odd']}x | Vincita: €{data['vincita']}")
    img = genera_immagine(data)
    print(f"Immagine: {'OK' if img else 'fallback testo'}")
    msg_id = pubblica_telegram(data, img, bookmaker, link)
    try:
        salva_sheet(data, msg_id, bookmaker)
    except Exception as e:
        print(f"Sheet error (non bloccante): {e}")
    print("=== DONE ===")
