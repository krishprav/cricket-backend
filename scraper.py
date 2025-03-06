import requests
from bs4 import BeautifulSoup
import json
import sys
import logging
from urllib.parse import urljoin

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BASE_URL = "https://www.cricbuzz.com"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def get_live_matches():
    """Fetch a list of live matches from Cricbuzz."""
    url = f"{BASE_URL}/cricket-match/live-scores"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        match_blocks = soup.find_all("div", class_="cb-lv-scrs-col")  # Updated selector for live scores
        matches = []
        for block in match_blocks:
            link = block.find_parent("a", href=True)
            if link and "href" in link.attrs:
                match_id = link["href"].split("/")[-2]  # Extract match ID
                teams_elem = block.find_previous("h3", class_="cb-lv-scrs-hdr")
                teams = teams_elem.text.strip() if teams_elem else "Unknown vs Unknown"
                score = block.text.strip() if block.text.strip() else "0/0"
                status_elem = block.find_next("div", class_="cb-text-live") or block.find_next("div", class_="cb-text-complete")
                status = status_elem.text.strip() if status_elem else "In progress"
                matches.append({"matchId": match_id, "teams": teams, "score": score, "status": status})
        logger.info(f"Found {len(matches)} live matches")
        return matches if matches else [{"matchId": "default", "teams": "No live matches", "score": "0/0", "status": "N/A"}]  # Fallback
    except requests.RequestException as e:
        logger.error(f"Error scraping live matches: {e}")
        return [{"matchId": "default", "teams": "Error fetching live matches", "score": "0/0", "status": "N/A"}]

def get_match_details(match_id):
    """Fetch detailed data for a specific match."""
    url = f"{BASE_URL}/live-cricket-scores/{match_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        
        match_info = {"matchId": match_id}
        
        # Basic match info
        score_elem = soup.find("div", class_="cb-min-bat-rw")
        match_info["score"] = score_elem.text.strip() if score_elem else "0/0"
        teams_elem = soup.find("span", class_="cb-lv-scrs-well-team-short")
        match_info["teams"] = teams_elem.text.strip() if teams_elem else "Unknown vs Unknown"
        
        # Detect events
        score_text = match_info["score"].lower()
        if '6' in score_text:
            match_info["event"] = "six"
        elif '4' in score_text:
            match_info["event"] = "four"
        elif '50' in score_text:
            match_info["event"] = "fifty"
        elif '100' in score_text:
            match_info["event"] = "hundred"
        
        # Commentary
        commentary_elems = soup.find_all("div", class_="cb-com-ln")
        match_info["commentary"] = [comm.text.strip() for comm in commentary_elems] if commentary_elems else []
        
        # Scorecard (basic parsing)
        scorecard_elems = soup.find_all("div", class_="cb-col cb-col-100 cb-scrd-itms")
        match_info["scorecard"] = {
            "batting": [s.text.strip() for s in scorecard_elems if "batting" in s.get_text().lower()[:10]],
            "bowling": [s.text.strip() for s in scorecard_elems if "bowling" in s.get_text().lower()[:10]]
        } if scorecard_elems else {"batting": [], "bowling": []}
        
        # Squads (from playing XI)
        squads_elems = soup.find_all("div", class_="cb-minfo-tm-nm")
        match_info["squads"] = {
            "team1": [s.text.strip() for s in squads_elems[:11]],
            "team2": [s.text.strip() for s in squads_elems[11:22]] if len(squads_elems) > 11 else []
        } if squads_elems else {"team1": [], "team2": []}
        
        # Points Table (placeholder)
        match_info["pointsTable"] = {"note": "Fetch from tournament page in future"}
        
        logger.info(f"Successfully scraped match {match_id}")
        return match_info
    except requests.RequestException as e:
        logger.error(f"Error scraping match {match_id}: {e}")
        return None

if __name__ == "__main__":
    match_id = sys.argv[1] if len(sys.argv) > 1 else "list"
    if match_id == "list":
        matches = get_live_matches()
        print(json.dumps(matches))
    else:
        data = get_match_details(match_id)
        if data:
            print(json.dumps(data))
        else:
            print(json.dumps({"matchId": match_id, "error": "Match data unavailable"}))
