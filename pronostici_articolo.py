import requests
import hashlib
import os
import time
import re
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta

# ─── CONFIG ──────────────────────────────────────────────────
BOT_TOKEN       = os.environ["BOT_TOKEN"]
CHAT_ID         = os.environ["CHAT_ID"]
ODDS_API_KEY    = os.environ["ODDS_API_KEY"]
# Groq API keys (PRIMARIO)
GROQ_API_KEYS = [k for k in [
    os.environ.get("GROQ_API_KEY", ""),
    os.environ.get("GROQ_API_KEY_2", ""),
] if k]
# Gemini API keys (FALLBACK)
GEMINI_API_KEYS = [k for k in [
    os.environ.get("GEMINI_API_KEY"),
    os.environ.get("GEMINI_API_KEY_2"),
    os.environ.get("GEMINI_API_KEY_3"),
    os.environ.get("GEMINI_API_KEY_4"),
    os.environ.get("GEMINI_API_KEY_5"),
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
def chiedi_groq(prompt):
    """Chiama Groq (llama-3.3-70b) — primario, 6.000 req/giorno free."""
    for key in GROQ_API_KEYS:
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "max_tokens": 1500,
                },
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"].strip()
            elif r.status_code == 429:
                print(f"Groq 429 su key ...{key[-6:]}")
                continue
        except Exception as e:
            print(f"Groq errore: {e}")
            continue
    return None


def chiedi_ai(prompt):
    """Groq (primario) → Gemini (fallback)."""
    if GROQ_API_KEYS:
        result = chiedi_groq(prompt)
        if result:
            return result
        print("Groq fallito — fallback su Gemini")
    return chiedi_gemini(prompt)


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
# ── 8 stili di analisi per variare i messaggi ────────────────
STILI_ANALISI = [
    {
        "nome": "tattico",
        "istruzione": (
            "Analizza la partita dal punto di vista TATTICO: schemi di gioco, "
            "equilibrio difesa vs attacco, pressing alto, transizioni veloci. "
            "Concludi con il tuo pronostico motivato tatticamente."
        ),
    },
    {
        "nome": "forma_recente",
        "istruzione": (
            "Concentrati sulla FORMA RECENTE: ultimi 5 risultati di entrambe le squadre, "
            "trend gol, striscia positiva o negativa, eventuale stanchezza da impegni ravvicinati. "
            "Pronostico basato sul momento attuale."
        ),
    },
    {
        "nome": "testa_a_testa",
        "istruzione": (
            "Parla dei PRECEDENTI storici tra le due squadre: chi domina nei testa a testa, "
            "tendenze (molti gol? equilibrio?), fattore campo. "
            "Pronostico ispirato alla storia tra le due squadre."
        ),
    },
    {
        "nome": "motivazionale",
        "istruzione": (
            "Analizza le MOTIVAZIONI in campo: chi ha più da perdere, situazione in classifica, "
            "obiettivi stagionali, pressione psicologica, spinta del pubblico di casa. "
            "Pronostico basato sull'intensità motivazionale."
        ),
    },
    {
        "nome": "statistico",
        "istruzione": (
            "Approccio STATISTICO: media gol segnati e subiti, rendimento casalingo vs trasferta, "
            "efficacia su palle inattive, clean sheet recenti. "
            "Pronostico supportato dai numeri."
        ),
    },
    {
        "nome": "narrativo",
        "istruzione": (
            "Racconta questa partita come una STORIA: il contesto della sfida, "
            "cosa rende questo match interessante, l'atmosfera attesa. "
            "Coinvolgi il lettore e concludi con il pronostico."
        ),
    },
    {
        "nome": "uomo_chiave",
        "istruzione": (
            "Identifica l'UOMO CHIAVE di ciascuna squadra: il giocatore più pericoloso, "
            "chi può fare la differenza, chi va tenuto d'occhio. "
            "Costruisci il pronostico attorno all'impatto di questi giocatori."
        ),
    },
    {
        "nome": "situazionale",
        "istruzione": (
            "Analizza i FATTORI SITUAZIONALI: turno di coppa o campionato, "
            "possibile turnover, trasferta lunga, assenze importanti, meteo. "
            "Pronostico tenendo conto di questi elementi extra-campo."
        ),
    },
]


def scegli_stile(home, away, orario):
    """Stile deterministico ma variato: stessa partita → stesso stile, partite diverse → stili diversi."""
    seed = f"{home}{away}{orario}"
    idx = int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(STILI_ANALISI)
    return STILI_ANALISI[idx]


def genera_messaggio_partita(p):
    stile = scegli_stile(p["home"], p["away"], p["orario_it"])
    print(f"    Stile: {stile['nome']}")

    prompt = f"""Sei un analista calcistico professionista italiano per il canale Telegram SuperPronostico.

Partita: {p["home"]} vs {p["away"]} | ore {p["orario_it"]} IT
Competizione: {p.get("competition", "Calcio Internazionale")}
Pronostico esperti SportyTrader: {p["tip"] or "N/D"}
Analisi disponibile: {p["analisi"][:500] if p["analisi"] else "N/D"}

STILE RICHIESTO — {stile["nome"].upper()}:
{stile["istruzione"]}

Scrivi UN messaggio Telegram (max 580 caratteri):
- Prima riga: *{p["home"]} vs {p["away"]}* | ore {p["orario_it"]} ⚽
- 2-3 righe di analisi nello stile indicato, professionale e coinvolgente
- Ultima riga: 🎯 *Pronostico: {p["tip"] or "da valutare"}*

REGOLE:
- Usa *grassetto* e _corsivo_ per enfatizzare
- Emoji pertinenti ma non esagerati
- Solo italiano
- NON includere le quote numeriche nel testo
- Restituisci solo il testo finale, nessun commento aggiuntivo."""
    return chiedi_ai(prompt)

def genera_tutti_messaggi(partite, now_it):
    messaggi = []
    data_it = now_it.strftime('%A %d %B %Y').capitalize()

    # Intestazione
    messaggi.append(
        f"🔥 *LE ANALISI DI OGGI — {data_it}* 🔥\n\n"
        f"⚽ {len(partite)} partite analizzate\n"
        f"📊 Analisi tattiche, statistiche e pronostici\n\n"
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