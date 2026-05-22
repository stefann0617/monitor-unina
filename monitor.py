#!/usr/bin/env python3
import hashlib
import os
import re
import sys
import time
import urllib.request
import requests

URL = "https://www.developeracademy.unina.it/en/enrollment/"
HASH_FILE = "last_hash.txt"
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]


def fetch_page(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def extract_section(html):
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
    return combined


def compute_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }, timeout=15)
    if not resp.json().get("ok"):
        print(f"[!] Telegram errore: {resp.text}")
    else:
        print("[+] Notifica Telegram inviata.")


def main():
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Controllo pagina...")

    html    = fetch_page(URL)
    section = extract_section(html)
    h       = compute_hash(section)

    if not os.path.exists(HASH_FILE):
        with open(HASH_FILE, "w") as f:
            f.write(h)
        print("[+] Primo avvio — stato iniziale salvato.")
        send_telegram(
            "✅ <b>Monitor UniNA avviato su GitHub!</b>\n"
            f"Controllo ogni ~5 minuti.\n"
            "Ti avviserò quando la graduatoria si aggiorna.\n\n"
            f"🔗 {URL}"
        )
        return

    with open(HASH_FILE) as f:
        old_hash = f.read().strip()

    if h != old_hash:
        print("[!!!] CAMBIAMENTO RILEVATO!")
        with open(HASH_FILE, "w") as f:
            f.write(h)
        send_telegram(
            "🚨 <b>AGGIORNAMENTO GRADUATORIA UNINA!</b>\n\n"
            "La pagina di enrollment della Developer Academy si è aggiornata!\n\n"
            f"🔗 <a href=\"{URL}\">Apri subito la pagina</a>\n\n"
            f"⏰ {time.strftime('%H:%M del %d/%m/%Y')}"
        )
    else:
        print("[-] Nessuna modifica.")


if __name__ == "__main__":
    main()
