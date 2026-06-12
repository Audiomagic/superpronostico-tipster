import requests
import os
import time
import re
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta

# ─── CONFIG ──────────────────────────────────────────────────
BOT_TOKEN       = os.environ["BOT_TOKEN"]
CHAT_ID         = os.environ["CHAT_ID"]
ODDS_API_KEY    = os.environ["ODDS_API_KEY"]
GEMINI_API_KEYS = [k for k in [
    os.environ.get("GEMINI_API_KEY"),
    os.environ.get("GEMINI_API_KEY_2"),
    os.environ.get("GEMINI_API_KEY_3"),
] if k]
GEMINI_MODELS = [
    "gemini-2.0-flash", "gemini-2.0-flash-lite",
    "gemini-2.5-flash", "gemini-flash-latest",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9",
}
BASE_URL   = "https://www.sportytrader.it"
IT_TZ      = timezone(timedelta(hours=2))

SPORTS_ODDS = [
    "soccer_fifa_world_cup",
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_italy_serie_a",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_germany_bundesliga",
    "soccer_france_ligue_one",
]

def get_now_it():
    return datetime.now(IT_TZ)

# ─── GEMINI ──────────────────────────────────────────────────
def chiedi_gemini(prompt):
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1500}
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

# ─── THE ODDS API — orari IT corretti ─────────────────────────
def fetch_partite_oggi_it():
    """Fetcha le partite di oggi con orari IT corretti da The Odds API."""
    now_it = get_now_it()
    # Finestra: dalle 08:00 di oggi fino alle 08:00 di domani (24h)
    inizio = now_it.replace(hour=8, minute=0, second=0, microsecond=0)
    fine   = inizio + timedelta(hours=24)
    print(f"Finestra partite: {inizio.strftime('%d/%m %H:%M')} → {fine.strftime('%d/%m %H:%M')} IT")
    partite = []
    for sport in SPORTS_ODDS:
        r = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport}/odds/",
            params={"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h",
                    "oddsFormat": "decimal", "dateFormat": "iso"},
            timeout=15
        )
        if r.status_code != 200:
            print(f"  {sport}: HTTP {r.status_code}")
            continue
        for g in r.json():
            ct = datetime.fromisoformat(g["commence_time"].replace("Z", "+00:00")).astimezone(IT_TZ)
            if not (inizio <= ct < fine):
                continue
            odds_1 = odds_x = odds_2 = None
            for bk in g.get("bookmakers", [])[:1]:
                for mkt in bk.get("markets", []):
                    if mkt["key"] == "h2h":
                        for o in mkt["outcomes"]:
                            if o["name"] == g["home_team"]: odds_1 = round(o["price"], 2)
                            elif o["name"] == g["away_team"]: odds_2 = round(o["price"], 2)
                            else: odds_x = round(o["price"], 2)
            partite.append({
                "home": g["home_team"],
                "away": g["away_team"],
                "sport": sport,
                "orario_it": ct.strftime("%H:%M"),
                "odds_1": odds_1 or "N/D",
                "odds_x": odds_x or "N/D",
                "odds_2": odds_2 or "N/D",
            })
            print(f"  {ct.strftime('%H:%M')} IT | {g['home_team']} vs {g['away_team']} | 1={odds_1} X={odds_x} 2={odds_2}")
    partite.sort(key=lambda x: x["orario_it"])
    return partite

# ─── SPORTYTRADER — pronostici e analisi ─────────────────────
def normalizza(nome):
    return (nome.lower()
        .replace("&", "").replace("-", " ")
        .replace("herzegovina", "erzegovina")
        .replace("  ", " ").strip())

def match_squadre(a, b):
    na, nb = normalizza(a), normalizza(b)
    if na == nb: return True
    if na in nb or nb in na: return True
    if len(na) >= 5 and na[:5] == nb[:5]: return True
    return False

def scrape_lista_sportytrader():
    """Scarica la lista dei link pronostici dalla pagina principale."""
    r = requests.get(f"{BASE_URL}/pronostici/calcio/", headers=HEADERS, timeout=15)
    if r.status_code != 200:
        return {}
    soup = BeautifulSoup(r.text, "html.parser")
    links = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"/pronostici/[a-z0-9-]+-\d{5,}/?$", href):
            full = href if href.startswith("http") else BASE_URL + href
            # Estrai home-away dal nome slug
            slug = full.rstrip("/").split("/")[-1]
            links[slug] = full
    return links

def scrape_pronostico_sporty(url):
    """Scrapa analisi e pronostico da una singola pagina SportyTrader."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None, None, None, None
        soup = BeautifulSoup(r.text, "html.parser")
        main = soup.select_one("main")
        if not main:
            return None, None, None, None

        lines = [l.strip() for l in main.get_text(separator="\n").split("\n") if l.strip()]

        # Estrai home/away
        home = away = tip = ""
        for i, line in enumerate(lines[:15]):
            if re.match(r"^\d{2}/\d{2}/\d{2}$", line):
                if i > 0: home = lines[i-1]
                if i+2 < len(lines): away = lines[i+2]
            if "Il pronostico:" in line and i+1 < len(lines):
                tip = lines[i+1]

        # Analisi testuale
        analisi_lines = []
        capture = False
        for line in lines:
            if capture:
                if len(line) > 60 and not any(x in line for x in ["Bookmaker","Bonus","Offerta","quote","Quote","Vedere","scommettere","Riservato","Pubblicato"]):
                    analisi_lines.append(line)
                if len(analisi_lines) >= 4:
                    break
            if line.startswith("Pronostico ") and len(line) > 15:
                capture = True

        analisi = " ".join(analisi_lines)
        return home, away, tip, analisi
    except:
        return None, None, None, None

def abbina_pronostici(partite_odds, links_sporty):
    """Abbina ogni partita Odds API con il pronostico SportyTrader."""
    risultati = []
    slugs = list(links_sporty.items())

    for p in partite_odds:
        trovato = False
        for slug, url in slugs:
            # Prova a leggere la pagina
            home_s, away_s, tip, analisi = scrape_pronostico_sporty(url)
            if not home_s:
                continue
            if match_squadre(p["home"], home_s) and match_squadre(p["away"], away_s):
                print(f"  MATCH: {p['home']} vs {p['away']} -> {url.split('/')[-2]}")
                risultati.append({**p, "tip": tip, "analisi": analisi, "url": url})
                trovato = True
                break
            time.sleep(0.2)

        if not trovato:
            print(f"  No pronostico SportyTrader per: {p['home']} vs {p['away']}")
            risultati.append({**p, "tip": "", "analisi": "", "url": ""})

    return risultati

# ─── GEMINI — genera messaggi ────────────────────────────────
def genera_messaggio_partita(p):
    q1 = f"@{p['odds_1']}" if p['odds_1'] != "N/D" else ""
    prompt = f"""Sei un analista calcistico professionista italiano per il canale Telegram SuperPronostico.

Partita: {p['home']} vs {p['away']} | ore {p['orario_it']} IT
Pronostico esperti SportyTrader: {p['tip'] or 'N/D'}
Quote: 1={p['odds_1']} X={p['odds_x']} 2={p['odds_2']}
Analisi disponibile: {p['analisi'][:400] if p['analisi'] else 'N/D'}

Scrivi UN messaggio Telegram (max 600 caratteri):
- Prima riga: *{p['home']} vs {p['away']}* ore {p['orario_it']} — _Mondiali_
- 2-3 righe analisi professionale e coinvolgente
- *Pronostico: {p['tip'] or 'da definire'}* {q1}
- Quote: 1={p['odds_1']} X={p['odds_x']} 2={p['odds_2']}

Regole: *grassetto*, _corsivo_, emoji ⚽🔥🎯, solo italiano, solo il testo."""
    return chiedi_gemini(prompt)

def genera_tutti_messaggi(partite, now_it):
    messaggi = []
    data_it = now_it.strftime('%A %d %B %Y').capitalize()

    # Intestazione
    messaggi.append(
        f"🔥 *LE ANALISI DI OGGI — {data_it}* 🔥\n\n"
        f"⚽ {len(partite)} partite analizzate\n"
        f"📊 Pronostici e quote in tempo reale\n\n"
        f"Seguici per non perdere nessuna analisi! 👇"
    )

    for i, p in enumerate(partite, 1):
        print(f"  Gemini analisi {i}/{len(partite)}: {p['home']} vs {p['away']}...")
        testo = genera_messaggio_partita(p)
        if testo:
            messaggi.append(testo)
        else:
            messaggi.append(
                f"*{p['home']} vs {p['away']}* ore {p['orario_it']}\n"
                f"🎯 *Pronostico: {p['tip'] or 'N/D'}*\n"
                f"Quote: 1={p['odds_1']} X={p['odds_x']} 2={p['odds_2']}"
            )

    messaggi.append("——————\n🔔 *Attiva le notifiche* per non perdere le analisi!\n⚠️ Solo per maggiorenni — gioca responsabilmente.")
    return messaggi

# ─── TELEGRAM ────────────────────────────────────────────────
def invia_messaggio(testo):
    if len(testo) > 4096:
        testo = testo[:4090] + "..."
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": testo, "parse_mode": "Markdown"}
    )
    result = r.json()
    if result.get("ok"):
        return result["result"]["message_id"]
    r2 = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": testo}
    )
    return r2.json().get("result", {}).get("message_id")

def pubblica_telegram(messaggi):
    ids = []
    for i, testo in enumerate(messaggi):
        msg_id = invia_messaggio(testo)
        if msg_id:
            print(f"  Messaggio {i+1}/{len(messaggi)} OK — id: {msg_id}")
            ids.append(msg_id)
        time.sleep(1)
    return ids

# ─── MAIN ────────────────────────────────────────────────────
if __name__ == "__main__":
    now = get_now_it()
    print(f"=== PRONOSTICI ARTICOLO — {now.strftime('%d/%m/%Y %H:%M')} IT ===")

    # Step 1: orari IT corretti da The Odds API
    print("\nFetch partite di oggi da The Odds API (orari IT)...")
    partite = fetch_partite_oggi_it()
    print(f"Partite trovate oggi dalle 08:00 IT: {len(partite)}")

    if not partite:
        print("Nessuna partita oggi. Stop.")
        exit(0)

    # Step 2: pronostici e analisi da SportyTrader
    print("\nScraping lista pronostici SportyTrader...")
    links = scrape_lista_sportytrader()
    print(f"Link trovati: {len(links)}")

    print("\nAbbinamento partite con pronostici...")
    partite = abbina_pronostici(partite[:8], links)

    # Step 3: genera messaggi con Gemini
    print("\nGenerazione messaggi con Gemini...")
    messaggi = genera_tutti_messaggi(partite, now)
    print(f"Messaggi generati: {len(messaggi)}")

    # Step 4: pubblica su Telegram
    print("\nPubblicazione su Telegram...")
    ids = pubblica_telegram(messaggi)
    print(f"\n=== DONE — {len(ids)} messaggi pubblicati ===")
