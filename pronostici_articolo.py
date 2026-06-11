import requests
import os
import time
import re
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta

# ─── CONFIG ──────────────────────────────────────────────────
BOT_TOKEN       = os.environ["BOT_TOKEN"]
CHAT_ID         = os.environ["CHAT_ID"]
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
BASE_URL = "https://www.sportytrader.it"

def get_now_it():
    return datetime.now(timezone(timedelta(hours=2)))

def chiedi_gemini(prompt):
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 3000}
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

def scrape_lista_pronostici():
    """Scrapa la pagina principale e trova i link dei pronostici di oggi."""
    r = requests.get(f"{BASE_URL}/pronostici/calcio/", headers=HEADERS, timeout=15)
    if r.status_code != 200:
        print(f"Errore fetch lista: {r.status_code}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    today = get_now_it().strftime("%d/%m/%y")

    # Trova tutti i link pronostici (hanno un numero ID alla fine)
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Link tipo /pronostici/nome-squadra1-nome-squadra2-123456/
        if re.search(r"/pronostici/[a-z0-9-]+-\d{5,}/?$", href):
            full = href if href.startswith("http") else BASE_URL + href
            links.add(full)

    print(f"Link pronostici trovati: {len(links)}")
    return list(links)

def scrape_pronostico(url, oggi_str):
    """Scrapa una singola pagina pronostico e restituisce i dati strutturati.
    oggi_str = data di oggi in formato GG/MM/AA (es. '12/06/26')
    Filtra solo partite di OGGI tra le 08:00 e le 23:59 IT.
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        main = soup.select_one("main")
        if not main:
            return None

        lines = [l.strip() for l in main.get_text(separator="\n").split("\n") if l.strip()]

        # Estrai dati strutturati
        home = away = orario = data_partita = competizione = pronostico_tip = analisi = ""
        odds_1 = odds_x = odds_2 = "N/D"

        # Cerca data, orario e squadre (nelle prime righe)
        for i, line in enumerate(lines[:15]):
            if re.match(r"^\d{2}/\d{2}/\d{2}$", line):
                data_partita = line  # es. "12/06/26" — già in orario IT
                # Orario è la riga successiva
                if i + 1 < len(lines) and re.match(r"^\d{2}:\d{2}$", lines[i+1]):
                    orario = lines[i+1]
                # Home è la riga precedente, Away è 2 righe dopo
                if i > 0:
                    home = lines[i-1]
                if i + 2 < len(lines):
                    away = lines[i+2]
            if any(k in line for k in ["Mondiali", "Serie A", "Champions", "Premier", "Europa", "Liga", "Bundesliga", "Ligue", "Conference"]):
                competizione = line.replace("Pronostico ", "").replace("Mondo - ", "")

        # FILTRO 1: solo partite di OGGI
        if data_partita != oggi_str:
            print(f"    ⏭ Skip {home} vs {away} — data {data_partita} (oggi={oggi_str})")
            return None

        # FILTRO 2: solo partite dalle 08:00 alle 23:59 IT
        if orario:
            ora_h = int(orario.split(":")[0])
            if ora_h < 8:
                print(f"    ⏭ Skip {home} vs {away} — orario {orario} (prima delle 08:00)")
                return None

        # Cerca il pronostico (riga dopo "Il pronostico:")
        for i, line in enumerate(lines):
            if "Il pronostico:" in line and i + 1 < len(lines):
                pronostico_tip = lines[i+1]
                break

        # Analisi testuale (righe lunghe dopo "Pronostico [Competizione]")
        analisi_lines = []
        capture = False
        for line in lines:
            if capture:
                if len(line) > 60 and not any(x in line for x in ["Bookmaker", "Bonus", "Offerta", "quote", "Quote", "Vedere tutte", "scommettere"]):
                    analisi_lines.append(line)
                if len(analisi_lines) >= 4:
                    break
            if line.startswith("Pronostico ") and any(x in line for x in ["Mondiali", "Serie A", "Champions", "Premier", "Europa", "Liga", "Bundesliga", "Ligue"]):
                capture = True
        analisi = " ".join(analisi_lines)

        # Quote: pattern "1 X 2" poi righe con numeri
        quote_section = False
        quote_rows = []
        for i, line in enumerate(lines):
            if line == "1" and i+1 < len(lines) and lines[i+1] == "X":
                quote_section = True
                continue
            if quote_section and re.match(r"^\d\.\d+$", line):
                quote_rows.append(line)
            if len(quote_rows) >= 3:
                break

        if len(quote_rows) >= 3:
            odds_1, odds_x, odds_2 = quote_rows[0], quote_rows[1], quote_rows[2]

        # Fallback: usa il selettore CSS per le quote
        if odds_1 == "N/D":
            quote_els = main.select(".pastille--cotes")
            vals = [el.get_text(strip=True) for el in quote_els if re.match(r"^\d\.\d+$", el.get_text(strip=True))]
            if len(vals) >= 3:
                odds_1, odds_x, odds_2 = vals[0], vals[1], vals[2]

        if not home or not away:
            return None

        return {
            "url": url,
            "home": home,
            "away": away,
            "orario": orario,
            "competizione": competizione or "Calcio",
            "pronostico_tip": pronostico_tip,
            "analisi": analisi,
            "odds_1": odds_1,
            "odds_x": odds_x,
            "odds_2": odds_2,
        }
    except Exception as e:
        print(f"Errore scraping {url}: {e}")
        return None

def genera_messaggio_partita(p, now_it):
    """Gemini genera l'analisi per UNA singola partita."""
    q1 = f"@{p['odds_1']}" if p['odds_1'] != "N/D" else ""
    prompt = f"""Sei un analista calcistico professionista italiano per il canale Telegram SuperPronostico.

Partita: {p['home']} vs {p['away']} | {p['competizione']} | ore {p['orario']}
Pronostico esperti: {p['pronostico_tip']}
Quote: 1={p['odds_1']} X={p['odds_x']} 2={p['odds_2']}
Analisi disponibile: {p['analisi'][:400] if p['analisi'] else 'N/D'}

Scrivi UN messaggio Telegram per questa partita:
- Prima riga: *{p['home']} vs {p['away']}* ore {p['orario']} — _{p['competizione']}_
- 3-4 righe di analisi professionale e coinvolgente
- *🎯 Pronostico: [{p['pronostico_tip']}]* con quota se disponibile
- Riga quote: 1={p['odds_1']} ❌ X={p['odds_x']} ❌ 2={p['odds_2']}

Regole: *grassetto*, _corsivo_, emoji, max 600 caratteri, solo italiano, solo il testo."""
    return chiedi_gemini(prompt)

def genera_post_telegram(pronostici, now_it):
    """Genera lista di messaggi: intestazione + uno per partita + chiusura."""
    messaggi = []

    # Messaggio 1: intestazione
    data_it = now_it.strftime('%A %d %B %Y').capitalize()
    intestazione = f"🔥 *LE ANALISI DI OGGI — {data_it}* 🔥\n\n⚽ {len(pronostici)} partite analizzate dai nostri esperti\n📊 Pronostici, quote e consigli per ogni match\n\nSeguici per non perdere nessuna analisi! 👇"
    messaggi.append(intestazione)

    # Un messaggio per ogni partita
    for i, p in enumerate(pronostici, 1):
        print(f"  Gemini analisi {i}/{len(pronostici)}: {p['home']} vs {p['away']}...")
        testo = genera_messaggio_partita(p, now_it)
        if testo:
            messaggi.append(testo)
        else:
            # Fallback senza Gemini
            fallback = f"*{p['home']} vs {p['away']}* ore {p['orario']} — _{p['competizione']}_\n\n🎯 *Pronostico: {p['pronostico_tip']}*\n\nQuote: 1={p['odds_1']} X={p['odds_x']} 2={p['odds_2']}"
            messaggi.append(fallback)

    # Messaggio finale: chiusura
    chiusura = "——————\n🔔 *Attiva le notifiche* per non perdere le prossime analisi!\n\n⚠️ Solo per maggiorenni — gioca responsabilmente. Le analisi sono a scopo informativo."
    messaggi.append(chiusura)

    return messaggi

def invia_messaggio(testo):
    """Invia un singolo messaggio Telegram."""
    if len(testo) > 4096:
        testo = testo[:4090] + "..."
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": testo, "parse_mode": "Markdown"}
    )
    result = r.json()
    if result.get("ok"):
        return result["result"]["message_id"]
    # Fallback senza markdown
    r2 = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": testo}
    )
    return r2.json().get("result", {}).get("message_id")

def pubblica_telegram(messaggi):
    """Pubblica una lista di messaggi su Telegram con pausa tra uno e l'altro."""
    ids = []
    for i, testo in enumerate(messaggi):
        msg_id = invia_messaggio(testo)
        if msg_id:
            print(f"  ✅ Messaggio {i+1}/{len(messaggi)} — id: {msg_id}")
            ids.append(msg_id)
        else:
            print(f"  ❌ Messaggio {i+1} fallito")
        time.sleep(1)  # pausa 1s tra messaggi
    return ids

if __name__ == "__main__":
    now = get_now_it()
    print(f"=== PRONOSTICI SPORTYTRADER — {now.strftime('%d/%m/%Y %H:%M')} ===")

    # Step 1: lista link
    print("\nScraping lista pronostici SportyTrader...")
    urls = scrape_lista_pronostici()

    if not urls:
        print("Nessun pronostico trovato. Stop.")
        exit(0)

    # Step 2: scrapa ogni pagina
    print(f"\nScraping {len(urls)} pagine pronostici...")
    pronostici = []
    oggi_str = now.strftime("%d/%m/%y")  # es. "12/06/26"
    print(f"Filtro partite per oggi: {oggi_str} dalle 08:00 alle 23:59 IT")

    for url in urls:  # scorriamo tutti, filtro interno
        print(f"  {url.split('/')[-2]}")
        dati = scrape_pronostico(url, oggi_str)
        if dati:
            pronostici.append(dati)
            print(f"    ✅ {dati['home']} vs {dati['away']} | tip: {dati['pronostico_tip']} | 1={dati['odds_1']} X={dati['odds_x']} 2={dati['odds_2']}")
        time.sleep(0.5)

    print(f"\nPronostici raccolti: {len(pronostici)}")

    # Limita a max 8 partite per non fare il post troppo lungo
    pronostici = pronostici[:8]

    if not pronostici:
        print("Nessun pronostico valido per oggi. Stop.")
        exit(0)

    # Step 3: genera post con Gemini
    messaggi = genera_post_telegram(pronostici, now)
    print(f"\nMessaggi generati: {len(messaggi)}")

    # Step 4: pubblica
    print("\nPubblicazione Telegram...")
    ids = pubblica_telegram(messaggi)
    print(f"Pubblicati {len(ids)} messaggi su Telegram.")

    print("\n=== DONE ===")
