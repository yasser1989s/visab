import os
import json
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime

DOS_ROOT = "https://travel.state.gov"
DOS_PORTAL = "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html"
DATA_FILE = "data/current_bulletin.json"
AI_API_KEY = os.getenv("AI_API_KEY")

MONTH_MAP = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
    "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
    "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12"
}

def clean_date(val):
    val = val.strip().upper()
    if val in ["C", "CURRENT"]:
        return "Current"
    if val in ["U", "UNAUTHORIZED"]:
        return "Unavailable"
    
    # Matches patterns like 01SEP23, 01-SEP-2023, or 1SEP23
    m = re.match(r"^(\d{1,2})[- ]?([A-Z]{3})[- ]?(\d{2,4})$", val)
    if m:
        day = m.group(1).zfill(2)
        mon = MONTH_MAP.get(m.group(2)[:3], "01")
        yr = m.group(3)
        if len(yr) == 2:
            yr = f"20{yr}" if int(yr) < 50 else f"19{yr}"
        return f"{yr}-{mon}-{day}"
    return val

def parse_dos_table(table):
    results = {}
    if not table:
        return results
    for row in table.find_all("tr"):
        cols = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if len(cols) >= 2:
            cat = cols[0].upper().replace("-", "").strip()
            date_clean = clean_date(cols[1])

            if "F1" in cat: results["F1"] = date_clean
            elif "F2A" in cat: results["F2A"] = date_clean
            elif "F2B" in cat: results["F2B"] = date_clean
            elif "F3" in cat: results["F3"] = date_clean
            elif "F4" in cat: results["F4"] = date_clean
            elif "1ST" in cat or "EB1" in cat: results["EB1"] = date_clean
            elif "2ND" in cat or "EB2" in cat: results["EB2"] = date_clean
            elif "3RD" in cat and "OTHER" not in cat: results["EB3"] = date_clean
            elif "OTHER WORKERS" in cat: results["EB3_Other"] = date_clean
            elif "4TH" in cat or "EB4" in cat: results["EB4"] = date_clean
            elif "5TH" in cat or "EB5" in cat: results["EB5_Unreserved"] = date_clean
    return results

def generate_ai_insights(bulletin_month, dates_summary):
    if not AI_API_KEY:
        print("[!] Note: AI_API_KEY not set. Retaining analytical baseline.")
        return []
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={AI_API_KEY}"
    prompt = f"""
    Act as a senior US Immigration Data Scientist. The official Visa Bulletin for '{bulletin_month}' has just published.
    Here is the cut-off dates data: {json.dumps(dates_summary)}

    Generate 4 structured analytical insights for upcoming months.
    Output strictly valid JSON (no markdown formatting, no backticks, just raw json):
    [
      {{
        "category": "Category name",
        "trend": "Bullish / Steady Progression / Retrogression Risk / Current",
        "summary": "1-2 sentence analytical forecast on movement for next 3-6 months based on quota limits",
        "actionable_tip": "Direct actionable legal filing strategy for applicants"
      }}
    ]
    """
    try:
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=20)
        res_json = res.json()
        raw_text = res_json['candidates'][0]['content']['parts'][0]['text']
        cleaned = re.sub(r'```json|```', '', raw_text).strip()
        return json.loads(cleaned)
    except Exception as e:
        print(f"[!] AI generation error: {e}")
        return []

def run():
    print("[*] Checking Department of State Visa Bulletin portal...")
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(DOS_PORTAL, headers=headers, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")
    except Exception as e:
        print(f"[!] Portal fetch error: {e}")
        return

    link = soup.find("a", string=lambda t: t and "visa bulletin for" in t.lower())
    if not link:
        print("[-] Bulletin link not found.")
        return

    bulletin_name = link.get_text(strip=True)
    bulletin_url = link["href"]
    if not bulletin_url.startswith("http"):
        bulletin_url = DOS_ROOT + bulletin_url

    print(f"[+] Found bulletin: {bulletin_name} -> {bulletin_url}")

    try:
        b_res = requests.get(bulletin_url, headers=headers, timeout=15)
        b_soup = BeautifulSoup(b_res.text, "html.parser")
        tables = b_soup.find_all("table")
    except Exception as e:
        print(f"[!] Error fetching bulletin page: {e}")
        return

    if not os.path.exists(DATA_FILE):
        return

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    data["bulletin_month"] = bulletin_name
    data["last_scraped_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    if len(tables) >= 4:
        f_final = parse_dos_table(tables[0])
        f_filing = parse_dos_table(tables[1])
        e_final = parse_dos_table(tables[2])
        e_filing = parse_dos_table(tables[3])

        for k, v in f_final.items():
            if k in data.get("family_based", {}):
                data["family_based"][k]["final_action_date"] = v
        for k, v in f_filing.items():
            if k in data.get("family_based", {}):
                data["family_based"][k]["filing_date"] = v
        for k, v in e_final.items():
            if k in data.get("employment_based", {}):
                data["employment_based"][k]["final_action_date"] = v
        for k, v in e_filing.items():
            if k in data.get("employment_based", {}):
                data["employment_based"][k]["filing_date"] = v

    ai_results = generate_ai_insights(bulletin_name, {
        "family": {k: v.get("final_action_date") for k, v in data.get("family_based", {}).items()},
        "employment": {k: v.get("final_action_date") for k, v in data.get("employment_based", {}).items()}
    })
    if ai_results:
        data["ai_insights"] = ai_results

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print("[✓] Automatically updated current_bulletin.json successfully.")

if __name__ == "__main__":
    run()
