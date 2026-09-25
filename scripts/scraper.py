import os
import json
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime

DOS_MAIN_URL = "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html"
DATA_FILE = "data/current_bulletin.json"
AI_API_KEY = os.getenv("AI_API_KEY")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
}

def parse_bulletin_table(table):
    """Extract preference categories and their cut-off dates from HTML table"""
    results = {}
    if not table:
        return results
    
    rows = table.find_all("tr")
    for r in rows:
        cols = [c.get_text(strip=True) for c in r.find_all(["td", "th"])]
        if len(cols) >= 2:
            cat = cols[0].upper().replace("-", "").strip()
            date_val = cols[1].strip()
            
            # Map standard abbreviations
            if "F1" in cat: results["F1"] = date_val
            elif "F2A" in cat: results["F2A"] = date_val
            elif "F2B" in cat: results["F2B"] = date_val
            elif "F3" in cat: results["F3"] = date_val
            elif "F4" in cat: results["F4"] = date_val
            elif "1ST" in cat or "EB1" in cat: results["EB1"] = date_val
            elif "2ND" in cat or "EB2" in cat: results["EB2"] = date_val
            elif "3RD" in cat and "OTHER" not in cat: results["EB3"] = date_val
            elif "OTHER WORKERS" in cat: results["EB3_Other"] = date_val
            elif "4TH" in cat or "EB4" in cat: results["EB4"] = date_val
            elif "5TH" in cat or "EB5" in cat: results["EB5_Unreserved"] = date_val
            
    return results

def generate_ai_insights(bulletin_month, dates_summary):
    """Generate professional AI immigration forecasts using Gemini API"""
    if not AI_API_KEY:
        print("[!] Warning: AI_API_KEY not found in secrets. Using default analytical forecast.")
        return [
            {
                "category": "F2A (Spouses & Minors of LPRs)",
                "trend": "Bullish (Rapid Movement)",
                "summary": "High quota allocation at start of fiscal year accelerates Chart B filings.",
                "actionable_tip": "File I-485 concurrently if your priority date precedes the filing cut-off."
            },
            {
                "category": "EB-2 / EB-3 (Skilled & NIW)",
                "trend": "Moderate Progression",
                "summary": "Quarterly allocation limits maintain steady advancement (+15 to 30 days/month).",
                "actionable_tip": "Audit premium processing availability for underlying I-140 petitions."
            }
        ]
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={AI_API_KEY}"
    prompt = f"""
    Act as a veteran US Immigration Data Analyst. The new Department of State Visa Bulletin for '{bulletin_month}' has just been published.
    Here is the cut-off dates data: {json.dumps(dates_summary)}

    Generate a structured JSON array with 4 sharp analytical forecasts for upcoming months.
    Output strictly valid JSON with this exact schema (no markdown fences, just pure JSON):
    [
      {{
        "category": "Category name",
        "trend": "Rapid / Steady / Retrogression Risk",
        "summary": "Brief 1-2 sentence analytical forecast on what will happen in the coming 3-6 months",
        "actionable_tip": "Direct advice for applicants regarding I-485 or consular processing"
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
        print(f"[!] AI generation encountered an error: {e}")
        return []

def run_pipeline():
    print("[*] Checking for latest Visa Bulletin...")
    try:
        resp = requests.get(DOS_MAIN_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"[!] Failed to fetch portal: {e}")
        return

    soup = BeautifulSoup(resp.text, "html.parser")
    latest_link = soup.find("a", string=lambda t: t and "visa bulletin for" in t.lower())
    
    if not latest_link:
        print("[-] No bulletin links found.")
        return

    bulletin_title = latest_link.get_text(strip=True)
    bulletin_href = latest_link["href"]
    if not bulletin_href.startswith("http"):
        bulletin_href = "https://travel.state.gov" + bulletin_href

    print(f"[+] Found bulletin: {bulletin_title} -> {bulletin_href}")

    # Scrape actual bulletin page
    b_resp = requests.get(bulletin_href, headers=HEADERS, timeout=15)
    b_soup = BeautifulSoup(b_resp.text, "html.parser")
    tables = b_soup.find_all("table")

    # Read existing database
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"family_based": {}, "employment_based": {}}

    data["bulletin_month"] = bulletin_title
    data["last_scraped_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    # If new tables exist, extract cut-off dates
    if len(tables) >= 4:
        chart_a_family = parse_bulletin_table(tables[0])
        chart_b_family = parse_bulletin_table(tables[1])
        chart_a_emp = parse_bulletin_table(tables[2])
        chart_b_emp = parse_bulletin_table(tables[3])

        for k, v in chart_a_family.items():
            if k in data.get("family_based", {}):
                data["family_based"][k]["final_action_date"] = v
        for k, v in chart_b_family.items():
            if k in data.get("family_based", {}):
                data["family_based"][k]["filing_date"] = v
        for k, v in chart_a_emp.items():
            if k in data.get("employment_based", {}):
                data["employment_based"][k]["final_action_date"] = v
        for k, v in chart_b_emp.items():
            if k in data.get("employment_based", {}):
                data["employment_based"][k]["filing_date"] = v

    # Trigger AI analysis
    print("[*] Generating AI immigration projections...")
    ai_insights = generate_ai_insights(bulletin_title, {
        "family": {k: v.get("final_action_date") for k, v in data.get("family_based", {}).items()},
        "employment": {k: v.get("final_action_date") for k, v in data.get("employment_based", {}).items()}
    })
    
    if ai_insights:
        data["ai_insights"] = ai_insights

    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        
    print("[✓] Scraping and AI analysis completed successfully.")

if __name__ == "__main__":
    run_pipeline()
