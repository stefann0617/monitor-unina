#!/usr/bin/env python3
"""
Monitor per la graduatoria Developer Academy UniNA.
Controlla ogni 5 min (via GitHub Actions) la sezione "Apple Developer Academy Updates".
Quando appare un nuovo PDF, lo analizza cercando Stefano Annunziata (score + admitted).
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
TELEGRAM_CHAT_ID   = "1212598951"   # solo Stefano

URL_DA_MONITORARE  = "https://www.developeracademy.unina.it/en/enrollment/"
BASE_URL           = "https://www.developeracademy.unina.it"
STATE_FILE         = os.path.join(os.path.dirname(__file__), "monitor_unina_state.json")

NOME_DA_CERCARE    = "Stefano Annunziata"
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


def resolve_url(href: str) -> str:
    if href.startswith("http"):
        return href
    return BASE_URL + href


def extract_updates_section(html: str) -> tuple:
    """
    Estrae solo la sezione 'Apple Developer Academy Updates'.
    Ritorna (hash_sezione, lista di (url_completo, etichetta)).
    """
    # Trova il blocco tra "Apple Developer Academy Updates" e "Apple Programs Participants Updates"
    match = re.search(
        r"Apple Developer Academy Updates.*?(<ul>.*?</ul>)",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return "", []

    section_html = match.group(1)

    # Estrai tutti i link PDF con la loro etichetta testuale
    items = re.findall(
        r'<a\s+href=["\']([^"\']+\.pdf[^"\']*)["\'][^>]*>(.*?)</a>',
        section_html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    pdfs = [(resolve_url(href.strip()), re.sub(r"<[^>]+>", "", label).strip())
            for href, label in items]

    section_hash = hashlib.sha256(section_html.encode()).hexdigest()
    return section_hash, pdfs


def search_in_pdf(pdf_url: str, name: str) -> dict:
    """
    Scarica il PDF e cerca il nome.
    Ritorna dict con: found, admitted, score, position, row, pages.
    """
    result = {"found": False, "admitted": False, "score": None, "position": None, "row": None, "pages": 0, "error": None}

    if not HAS_PYPDF:
        result["error"] = "pypdf non installato"
        return result

    print(f"  [PDF] Scarico: {pdf_url}")
    try:
        data = fetch_url_bytes(pdf_url)
        reader = pypdf.PdfReader(io.BytesIO(data))
        lines = []
        for page in reader.pages:
            lines.extend((page.extract_text() or "").splitlines())
        result["pages"] = len(reader.pages)
    except Exception as e:
        result["error"] = str(e)
        return result

    name_lower = name.lower()
    # Prova anche cognome-nome (formato italiano)
    parts = name.strip().split()
    name_reversed = (parts[-1] + " " + " ".join(parts[:-1])).lower() if len(parts) >= 2 else name_lower

    for line in lines:
        line_lower = line.lower()
        if name_lower in line_lower or name_reversed in line_lower:
            print(f"  [PDF] Riga trovata: {line.strip()}")
            result["found"] = True
            result["row"] = line.strip()
            result["admitted"] = "admitted" in line_lower

            # Estrai score (numero intero, anche con * o ,)
            score_match = re.search(r'\b(\d+[\*,\.]?\d*)\b', line)
            if score_match:
                result["score"] = score_match.group(1)

            # Estrai posizione (primo numero della riga)
            pos_match = re.match(r'^\s*(\d+)\s', line)
            if pos_match:
                result["position"] = pos_match.group(1)

            break

    return result


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


def notify_new_pdf(label: str, pdf_url: str, res: dict):
    """Costruisce e invia la notifica Telegram per un nuovo PDF."""
    if res.get("error"):
        send_telegram(
            f"📋 <b>Nuovo documento pubblicato!</b>\n\n"
            f"📄 {label}\n"
            f"🔗 <a href=\"{pdf_url}\">Apri PDF</a>\n\n"
            f"⚠️ Errore analisi: {res['error']}\n"
            f"⏰ {time.strftime('%H:%M del %d/%m/%Y')}"
        )
        return

    if not res["found"]:
        send_telegram(
            f"📋 <b>Nuovo documento pubblicato!</b>\n\n"
            f"📄 {label}\n"
            f"🔗 <a href=\"{pdf_url}\">Apri PDF</a>\n\n"
            f"❌ <b>{NOME_DA_CERCARE}</b> non è presente nel documento.\n"
            f"({res['pages']} pagine analizzate)\n"
            f"⏰ {time.strftime('%H:%M del %d/%m/%Y')}"
        )
        return

    if res["admitted"]:
        emoji = "🎉"
        status_text = "✅ <b>ADMITTED</b>"
    else:
        emoji = "⚠️"
        status_text = "❌ Non admitted"

    score_text = f"📊 Score: <b>{res['score']}</b>\n" if res["score"] else ""
    pos_text   = f"🏅 Posizione: <b>{res['position']}</b>\n" if res["position"] else ""

    send_telegram(
        f"{emoji} <b>Nuovo documento: {label}</b>\n\n"
        f"👤 <b>{NOME_DA_CERCARE}</b>\n"
        f"{pos_text}"
        f"{score_text}"
        f"{status_text}\n\n"
        f"🔗 <a href=\"{pdf_url}\">Apri PDF</a>\n"
        f"⏰ {time.strftime('%H:%M del %d/%m/%Y')}"
    )


def check_once():
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Controllo pagina...")
    try:
        html = fetch_page(URL_DA_MONITORARE)
        section_hash, pdfs = extract_updates_section(html)
    except Exception as e:
        print(f"[!] Errore fetch: {e}")
        return

    if not section_hash:
        print("[!] Sezione 'Apple Developer Academy Updates' non trovata.")
        return

    state = load_state()
    known_urls = set(state.get("known_pdfs", []))
    old_hash   = state.get("section_hash")

    # Prima esecuzione
    if old_hash is None:
        state["section_hash"] = section_hash
        state["known_pdfs"]   = [url for url, _ in pdfs]
        state["first_seen"]   = time.strftime("%Y-%m-%d %H:%M:%S")
        save_state(state)
        print(f"[+] Stato iniziale salvato. {len(pdfs)} PDF rilevati nella sezione.")
        send_telegram(
            f"✅ <b>Monitor UniNA avviato!</b>\n\n"
            f"Monitoro la sezione <b>Apple Developer Academy Updates</b>\n"
            f"Cerco: <b>{NOME_DA_CERCARE}</b>\n\n"
            f"📄 PDF attualmente presenti: {len(pdfs)}\n"
            f"🔗 <a href=\"{URL_DA_MONITORARE}\">Pagina enrollment</a>"
        )
        return

    # Cerca nuovi PDF
    new_pdfs = [(url, label) for url, label in pdfs if url not in known_urls]

    if new_pdfs:
        print(f"[!!!] {len(new_pdfs)} NUOVO/I PDF RILEVATO/I!")
        for pdf_url, label in new_pdfs:
            print(f"  -> {label}: {pdf_url}")
            res = search_in_pdf(pdf_url, NOME_DA_CERCARE)
            notify_new_pdf(label, pdf_url, res)
            known_urls.add(pdf_url)

        state["section_hash"] = section_hash
        state["known_pdfs"]   = list(known_urls)
        state["last_change"]  = time.strftime("%Y-%m-%d %H:%M:%S")
        save_state(state)

    elif section_hash != old_hash:
        # La sezione è cambiata ma non ci sono nuovi PDF (es. testo modificato)
        print("[!] Sezione aggiornata (nessun nuovo PDF).")
        state["section_hash"] = section_hash
        save_state(state)
        send_telegram(
            f"🔔 <b>Aggiornamento sulla pagina UniNA</b>\n\n"
            f"La sezione è cambiata ma non ci sono nuovi PDF.\n"
            f"🔗 <a href=\"{URL_DA_MONITORARE}\">Controlla la pagina</a>\n"
            f"⏰ {time.strftime('%H:%M del %d/%m/%Y')}"
        )
    else:
        print("[-] Nessuna modifica.")


def main():
    print("=" * 55)
    print("  Monitor Graduatoria Developer Academy UniNA")
    print("=" * 55)

    if "--once" in sys.argv:
        check_once()
    else:
        print("Avvio loop continuo. Premi Ctrl+C per fermare.\n")
        while True:
            check_once()
            time.sleep(5 * 60)


if __name__ == "__main__":
    main()
