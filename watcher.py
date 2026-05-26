import json
import os
import hashlib
import requests
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SNAPSHOT_FILE = "snapshots.json"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    })

def get_page_hash(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        return hashlib.md5(text.encode()).hexdigest(), text[:500]
    except Exception as e:
        return None, str(e)

def load_snapshots():
    if os.path.exists(SNAPSHOT_FILE):
        with open(SNAPSHOT_FILE, "r") as f:
            return json.load(f)
    return {}

def save_snapshots(snapshots):
    with open(SNAPSHOT_FILE, "w") as f:
        json.dump(snapshots, f, indent=2)

def main():
    with open("policies.json", "r") as f:
        policies = json.load(f)

    snapshots = load_snapshots()
    changes_found = False

    for source in policies["sources"]:
        name = source["name"]
        url = source["url"]
        print(f"Checking: {name}")

        current_hash, preview = get_page_hash(url)

        if current_hash is None:
            send_telegram(f"⚠️ <b>Error scanning:</b> {name}\n{preview}")
            continue

        if name not in snapshots:
            snapshots[name] = {"hash": current_hash, "url": url}
            print(f"  → First scan saved for: {name}")
        elif snapshots[name]["hash"] != current_hash:
            changes_found = True
            snapshots[name]["hash"] = current_hash
            message = (
                f"🚨 <b>Policy Change Detected!</b>\n\n"
                f"<b>Platform:</b> {name}\n"
                f"<b>URL:</b> {url}\n\n"
                f"Something changed. Go check it manually."
            )
            send_telegram(message)
            print(f"  → CHANGE DETECTED: {name}")
        else:
            print(f"  → No change: {name}")

    save_snapshots(snapshots)

    if not changes_found:
        send_telegram("✅ Policy scan complete — no changes detected.")

if __name__ == "__main__":
    main()
