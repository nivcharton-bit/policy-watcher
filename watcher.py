import json
import os
import requests
from bs4 import BeautifulSoup
from difflib import unified_diff

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

def get_page_text(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        # Clean up excessive blank lines
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)
    except Exception as e:
        return None

def get_diff(old_text, new_text):
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    diff = list(unified_diff(old_lines, new_lines, lineterm=""))
    added = [l[1:] for l in diff if l.startswith("+") and not l.startswith("+++")]
    removed = [l[1:] for l in diff if l.startswith("-") and not l.startswith("---")]
    return added, removed

def summarize_with_ai(name, url, added, removed):
    try:
        added_text = "\n".join(added[:50])
        removed_text = "\n".join(removed[:50])

        prompt = f"""A platform policy page changed. Summarize what changed in 2-3 simple sentences in English.
        
Platform: {name}
URL: {url}

Text that was ADDED:
{added_text if added_text else "nothing"}

Text that was REMOVED:
{removed_text if removed_text else "nothing"}

Reply only with a short plain English summary. No bullet points, no formatting."""

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30
        )
        data = response.json()
        return data["content"][0]["text"]
    except Exception as e:
        return "Could not generate summary."

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

        current_text = get_page_text(url)

        if current_text is None:
            send_telegram(f"⚠️ <b>Error scanning:</b> {name}\n{url}")
            continue

        if name not in snapshots:
            snapshots[name] = {"text": current_text, "url": url}
            print(f"  → First scan saved for: {name}")
        elif snapshots[name]["text"] != current_text:
            changes_found = True

            added, removed = get_diff(snapshots[name]["text"], current_text)
            summary = summarize_with_ai(name, url, added, removed)

            # Build the changed text preview
            added_preview = "\n".join(added[:10])
            removed_preview = "\n".join(removed[:10])

            message = (
                f"🚨 <b>Policy Change Detected!</b>\n\n"
                f"<b>Platform:</b> {name}\n"
                f"<b>URL:</b> {url}\n\n"
            )

            if removed_preview:
                message += f"🗑 <b>Removed:</b>\n<i>{removed_preview[:300]}</i>\n\n"

            if added_preview:
                message += f"✅ <b>Added:</b>\n<i>{added_preview[:300]}</i>\n\n"

            message += f"💡 <b>In simple words:</b>\n{summary}"

            send_telegram(message)
            snapshots[name]["text"] = current_text
            print(f"  → CHANGE DETECTED: {name}")
        else:
            print(f"  → No change: {name}")

    save_snapshots(snapshots)

    if not changes_found:
        send_telegram("✅ Policy scan complete — no changes detected.")

if __name__ == "__main__":
    main()
