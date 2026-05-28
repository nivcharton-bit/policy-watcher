import json
import os
import requests
from difflib import unified_diff
from playwright.sync_api import sync_playwright

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SNAPSHOT_FILE = "snapshots.json"

def send_telegram(message):
    chat_ids = [TELEGRAM_CHAT_ID]
    group_id = os.environ.get("TELEGRAM_CHAT_ID_GROUP")
    if group_id and group_id != TELEGRAM_CHAT_ID:
        chat_ids.append(group_id)

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for chat_id in chat_ids:
        requests.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        })

def get_page_text(page, url):
    try:
        page.goto(url, wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(2000)  # give JS a moment to settle
        # Grab visible text from the body
        text = page.inner_text("body")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)
    except Exception as e:
        print(f"  Error: {e}")
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
        added_text = "\n".join(added[:60])
        removed_text = "\n".join(removed[:60])

        prompt = f"""A platform policy page changed. Summarize what actually changed in 2-4 simple sentences in plain English. Focus on what matters for someone running marketing/content accounts on this platform. If the change looks purely cosmetic (navigation, footer, formatting), say so clearly.

Platform: {name}
URL: {url}

Text that was ADDED:
{added_text if added_text else "nothing"}

Text that was REMOVED:
{removed_text if removed_text else "nothing"}

Reply only with the summary. No bullet points, no headers."""

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 400,
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

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

        for source in policies["sources"]:
            name = source["name"]
            url = source["url"]
            print(f"Checking: {name}")

            current_text = get_page_text(page, url)

            if current_text is None or len(current_text) < 200:
                send_telegram(f"⚠️ <b>Scan problem:</b> {name}\nPage returned too little content. Check the URL:\n{url}")
                continue

            if name not in snapshots:
                snapshots[name] = {"text": current_text, "url": url}
                print(f"  → First scan saved ({len(current_text)} chars)")
            elif snapshots[name]["text"] != current_text:
                changes_found = True
                added, removed = get_diff(snapshots[name]["text"], current_text)
                summary = summarize_with_ai(name, url, added, removed)

                added_preview = "\n".join(added[:12])
                removed_preview = "\n".join(removed[:12])

                message = (
                    f"🚨 <b>Policy Change Detected!</b>\n\n"
                    f"<b>Platform:</b> {name}\n"
                    f"<b>URL:</b> {url}\n\n"
                )
                if removed_preview:
                    message += f"🗑 <b>Removed:</b>\n<i>{removed_preview[:400]}</i>\n\n"
                if added_preview:
                    message += f"✅ <b>Added:</b>\n<i>{added_preview[:400]}</i>\n\n"
                message += f"💡 <b>In simple words:</b>\n{summary}"

                send_telegram(message)
                snapshots[name]["text"] = current_text
                print(f"  → CHANGE DETECTED")
            else:
                print(f"  → No change")

        browser.close()

    save_snapshots(snapshots)

    if not changes_found:
        send_telegram("✅ Policy scan complete — no changes detected.")

if __name__ == "__main__":
    main()
