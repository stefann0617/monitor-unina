#!/usr/bin/env python3
"""
Monitor per la graduatoria Developer Academy UniNA.
Controlla la pagina ogni N minuti e manda una notifica Telegram se cambia qualcosa.
Quando trova un nuovo PDF di ranking, cerca "Stefano Annunziata" e notifica l'esito.
"""

import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.request

import requests as _requests

try:
    import pypdf
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

# ─── CONFIGURAZIONE ────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = "8696132874:AAGZCvv1INxP6PM1sCut6smzAEE0y2fZ3h8"
TELEGRAM_CHAT_ID   = "1212598951"

URL_DA_MONITORARE  = "https://www.developeracademy.unina.it/en/enrollment/"
INTERVALLO_MINUTI  = 3           # controlla ogni 3 minuti
STATE_FILE         = os.path.join(os.path.dirname(__file__), "monitor_unina_state.json")

NOME_DA_CERCARE    = "Stefano Annunziata"
# Parole chiave nel nome del PDF che identificano la graduatoria finale
PDF_RANKING_KEYWORDS = ["final", "ranking", "graduator", "ammess", "decreto"]
# ───────────────────────────────────────────────────────────────────────────────


def fetch_url_bytes(url: str) -> bytes:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def fetch_page(url: str) -> str:
    return fetch_url_bytes(url).decode("utf-8", errors="replace")


def is_ranking_pdf(url: str) -> bool:
    url_lower = url.lower()
    return any(kw in url_lower for kw in PDF_RANKING_KEYWORDS)


def search_name_in_pdf(pdf_url: str, name: str) -> tuple:
    """
    Scarica il PDF, trova la riga con il nome e controlla se contiene "admitted".
    Ritorna (ammesso: bool, riga_trovata: str).
    """
    if not HAS_PYPDF:
        return False, "pypdf non installato — installa con: pip install pypdf"

    print(f"  [PDF] Scarico e analizzo: {pdf_url}")
    try:
        data = fetch_url_bytes(pdf_url)
        reader = pypdf.PdfReader(io.BytesIO(data))
        lines = []
        for page in reader.pages:
            text = page.extract_text() or ""
            lines.extend(text.splitlines())
    except Exception as e:
        return False, f"Errore lettura PDF: {e}"

    name_lower = name.lower()
    for line in lines:
        if name_lower in line.lower():
            admitted = "admitted" in line.lower()
            print(f"  [PDF] Riga trovata: {line.strip()}")
            return admitted, f"Riga: «{line.strip()}»"

    return False, f"Nome non trovato ({len(lines)} righe analizzate)"


def extract_section(html: str) -> tuple:
    """
    Estrae le sezioni rilevanti: link PDF, testi su graduatoria/ranking/updates.
    Ritorna (stringa_da_hashare, lista_pdf_links).
    """
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>",  "", html, flags=re.DOTALL | re.IGNORECASE)

    links = re.findall(r'href=["\']([^"\']+)["\']', html)
    pdf_links = sorted({l for l in links if ".pdf" in l.lower() or "decreto" in l.lower()})

    blocks = re.findall(
        r"((?:updates?|graduator|ranking|ammess|interview|colloqui|decreto)[^\n<]{0,300})",
        html,
        flags=re.IGNORECASE,
    )
    text_snippet = "\n".join(blocks[:30])

    combined = "LINKS:\n" + "\n".join(pdf_links) + "\n\nTEXT:\n" + text_snippet
    return combined, pdf_links


def compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def send_telegram(message: str):
    if TELEGRAM_BOT_TOKEN == "QUI_IL_TUO_BOT_TOKEN":
        print("[!] Configura TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nello script!")
        return
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = _requests.post(api_url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }, timeout=15)
        result = resp.json()
        if not result.get("ok"):
            print(f"[!] Telegram errore: {result}")
        else:
            print("[+] Notifica Telegram inviata.")
    except Exception as e:
        print(f"[!] Errore invio Telegram: {e}")


def check_new_ranking_pdfs(pdf_links: list, state: dict) -> dict:
    """Controlla se ci sono nuovi PDF di ranking e cerca il nome al loro interno."""
    checked = set(state.get("checked_pdfs", []))
    new_pdfs = [url for url in pdf_links if url not in checked and is_ranking_pdf(url)]

    for pdf_url in new_pdfs:
        print(f"  [PDF] Nuovo documento rilevato: {pdf_url}")
        found, info = search_name_in_pdf(pdf_url, NOME_DA_CERCARE)
        checked.add(pdf_url)

        if found:
            print(f"  [!!!] '{NOME_DA_CERCARE}' AMMESSO!")
            send_telegram(
                f"🎉 <b>SEI AMMESSO!</b>\n\n"
                f"<b>{NOME_DA_CERCARE}</b> risulta <b>admitted</b> nel documento!\n\n"
                f"ℹ️ {info}\n"
                f"📄 <a href=\"{pdf_url}\">Apri PDF</a>\n"
                f"⏰ {time.strftime('%H:%M:%S del %d/%m/%Y')}"
            )
        elif "Riga:" in info:
            # Nome trovato ma senza "admitted"
            print(f"  [!] '{NOME_DA_CERCARE}' trovato ma NON admitted.")
            send_telegram(
                f"⚠️ <b>Nome trovato ma non admitted</b>\n\n"
                f"<b>{NOME_DA_CERCARE}</b> è nel documento ma non risulta <b>admitted</b>.\n\n"
                f"ℹ️ {info}\n"
                f"📄 <a href=\"{pdf_url}\">Apri PDF</a>\n"
                f"⏰ {time.strftime('%H:%M:%S del %d/%m/%Y')}"
            )
        else:
            print(f"  [-] '{NOME_DA_CERCARE}' NON trovato nel PDF.")
            send_telegram(
                f"📋 <b>Nuovo PDF pubblicato</b>\n\n"
                f"<b>{NOME_DA_CERCARE}</b> non è presente nel documento.\n\n"
                f"ℹ️ {info}\n"
                f"📄 <a href=\"{pdf_url}\">Apri PDF</a>\n"
                f"⏰ {time.strftime('%H:%M:%S del %d/%m/%Y')}"
            )

    state["checked_pdfs"] = list(checked)
    return state


def check_once():
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Controllo pagina...")
    try:
        html             = fetch_page(URL_DA_MONITORARE)
        section, pdf_links = extract_section(html)
        h                = compute_hash(section)
    except Exception as e:
        print(f"[!] Errore fetch: {e}")
        return

    state = load_state()
    old_hash = state.get("hash")

    if old_hash is None:
        state["hash"] = h
        state["first_seen"] = time.strftime("%Y-%m-%d %H:%M:%S")
        state = check_new_ranking_pdfs(pdf_links, state)
        save_state(state)
        print("[+] Stato iniziale salvato. Monitoring avviato.")
        send_telegram(
            "✅ <b>Monitor UniNA avviato!</b>\n"
            f"Sto monitorando: {URL_DA_MONITORARE}\n"
            f"Cerco: <b>{NOME_DA_CERCARE}</b> nella graduatoria finale.\n"
            "Ti avviserò quando la pagina si aggiornerà."
        )
        return

    # Controlla sempre i nuovi PDF, indipendentemente dall'hash della pagina
    state = check_new_ranking_pdfs(pdf_links, state)

    if h != old_hash:
        print("[!!!] CAMBIAMENTO RILEVATO!")
        state["hash"]        = h
        state["last_change"] = time.strftime("%Y-%m-%d %H:%M:%S")
        save_state(state)
        send_telegram(
            "🚨 <b>AGGIORNAMENTO GRADUATORIA UNINA!</b>\n\n"
            "La pagina di enrollment della Developer Academy si è aggiornata!\n\n"
            f"🔗 <a href=\"{URL_DA_MONITORARE}\">Apri la pagina</a>\n\n"
            f"⏰ Rilevato alle: {time.strftime('%H:%M:%S del %d/%m/%Y')}"
        )
    else:
        print("[-] Nessuna modifica.")

    save_state(state)


def main():
    print("=" * 55)
    print("  Monitor Graduatoria Developer Academy UniNA")
    print("=" * 55)

    # Controlla configurazione
    if TELEGRAM_BOT_TOKEN == "QUI_IL_TUO_BOT_TOKEN":
        print("\n[ERRORE] Apri monitor_unina.py e inserisci:")
        print("  - TELEGRAM_BOT_TOKEN")
        print("  - TELEGRAM_CHAT_ID")
        print("\nCome ottenerli:")
        print("  1. Scrivi a @BotFather su Telegram -> /newbot -> copia il token")
        print("  2. Scrivi a @userinfobot su Telegram -> copia il tuo ID")
        sys.exit(1)

    # Modalità: loop continuo oppure singola esecuzione (per cron)
    if "--once" in sys.argv:
        check_once()
    else:
        print(f"Intervallo: ogni {INTERVALLO_MINUTI} minuti")
        print("Premi Ctrl+C per fermare.\n")
        while True:
            check_once()
            time.sleep(INTERVALLO_MINUTI * 60)


if __name__ == "__main__":
    main()
