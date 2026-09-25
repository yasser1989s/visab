import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime

DOS_URL = "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html"
DATA_FILE = "data/current_bulletin.json"

def fetch_latest_bulletin():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    print("[*] Checking Department of State website...")
    try:
        response = requests.get(DOS_URL, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"[!] Error fetching DOS page: {e}")
        return

    soup = BeautifulSoup(response.text, "html.parser")
    # Identify latest bulletin link
    latest_link = soup.find("a", string=lambda text: text and "visa bulletin for" in text.lower())
    
    if not latest_link:
        print("[-] No new bulletin release identified.")
        return

    bulletin_title = latest_link.get_text(strip=True)
    print(f"[+] Active bulletin detected: {bulletin_title}")

    # Read and update existing local JSON
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}

    data["bulletin_month"] = bulletin_title
    data["last_scraped_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        
    print("[✓] Bulletin dataset updated successfully.")

if __name__ == "__main__":
    fetch_latest_bulletin()
