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
    """Fetch a list of live matches from Cricbuzz with deduplication."""
    url = f"{BASE_URL}/cricket-match/live-scores"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        match_blocks = soup.find_all("div", class_="cb-lv-scrs-col")
        matches = []
        seen_match_ids = set()
        for block in match_blocks:
            link = block.find_parent("a", href=True)
            if link and "href" in link.attrs:
                match_id = link["href"].split("/")[-2]
                if match_id in seen_match_ids:
                    continue
                seen_match_ids.add(match_id)
                teams_elem = block.find_previous("h3", class_="cb-lv-scrs-hdr")
                teams = teams_elem.text.strip() if teams_elem else "Unknown vs Unknown"
                if "vs" not in teams.lower():
                    teams_parts = block.text.strip().split("vs")
                    teams = f"{teams_parts[0].strip()} vs {teams_parts[1].strip()}" if len(teams_parts) > 1 else teams
                score = block.text.strip().split("\n")[0] if block.text.strip() else "0/0"
                status_elem = block.find_next("div", class_="cb-text-live") or block.find_next("div", class_="cb-text-complete")
                status = status_elem.text.strip() if status_elem else "In progress"
                matches.append({"matchId": match_id, "teams": teams, "score": score, "status": status})
        logger.info(f"Found {len(matches)} unique live matches")
        return matches if matches else [{"matchId": "default", "teams": "No live matches", "score": "0/0", "status": "N/A"}]
    except requests.RequestException as e:
        logger.error(f"Error scraping live matches: {e}")
        return [{"matchId": "default", "teams": "Error fetching live matches", "score": "0/0", "status": "N/A"}]

def get_match_details(match_id):
    """Fetch detailed data for a specific match with improved parsing."""
    url = f"{BASE_URL}/live-cricket-scores/{match_id}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        
        match_info = {"matchId": match_id}
        
        # Teams and Logos
        teams_elem = soup.find("span", class_="cb-lv-scrs-well-team-short") or soup.find("h3", class_="cb-lv-scrs-hdr")
        teams_text = teams_elem.text.strip() if teams_elem else "Unknown vs Unknown"
        if "vs" not in teams_text.lower():
            score_block = soup.find("div", class_="cb-min-bat-rw")
            if score_block:
                teams_parts = [t.strip() for t in score_block.find_all("span", class_="cb-scrd-liv-btn")[:2]]
                teams_text = f"{teams_parts[0]} vs {teams_parts[1]}" if len(teams_parts) == 2 else teams_text
        match_info["teams"] = teams_text
        # Extract logos (assuming they are in img tags near team names)
        logo_elems = soup.find_all("img", class_="cb-img-bdy")
        logos = [urljoin(BASE_URL, img["src"]) for img in logo_elems[:2] if "src" in img.attrs] if logo_elems else []
        match_info["logos"] = {"team1": logos[0] if len(logos) > 0 else "", "team2": logos[1] if len(logos) > 1 else ""}
        
        # Score
        score_elem = soup.find("div", class_="cb-min-bat-rw") or soup.find("div", class_="cb-hmscg-bat-txt")
        match_info["score"] = score_elem.text.strip() if score_elem else "Score not available"
        crr_elem = soup.find("div", class_="cb-font-12", string=lambda t: "CRR" in t)
        match_info["crr"] = crr_elem.find_next("div").text.strip().split("CRR: ")[1] if crr_elem else "N/A"
        
        # Status
        status_elem = soup.find("div", class_="cb-text-live") or soup.find("div", class_="cb-text-complete")
        match_info["status"] = status_elem.text.strip() if status_elem else "N/A"
        
        # Events
        score_text = match_info["score"].lower()
        if '6' in score_text and 'over' not in score_text:
            match_info["event"] = "six"
        elif '4' in score_text and 'over' not in score_text:
            match_info["event"] = "four"
        elif '50' in score_text:
            match_info["event"] = "fifty"
        elif '100' in score_text:
            match_info["event"] = "hundred"
        
        # Commentary
        commentary_elems = soup.find_all("div", class_="cb-com-ln") or soup.find_all("div", class_="cb-comm-hist")
        match_info["commentary"] = [comm.text.strip() for comm in commentary_elems[:10]] if commentary_elems else ["No commentary available."]
        
        # Scorecard (Batter and Bowler Statistics)
        scorecard_table = soup.find("div", class_="cb-col cb-col-100 cb-scrd-itms")
        if scorecard_table:
            batters = []
            bowlers = []
            rows = scorecard_table.find_all("div", class_="cb-col cb-col-100 cb-scrd-itms")
            for row in rows:
                player_name = row.find("a", class_="cb-text-link")
                if player_name and "batting" in row.get_text().lower()[:10]:
                    stats = row.find_all("div", class_="cb-col cb-col-100 cb-scrd-itm")
                    if len(stats) >= 5:
                        batters.append({
                            "name": player_name.text.strip(),
                            "runs": stats[0].text.strip(),
                            "balls": stats[1].text.strip(),
                            "fours": stats[2].text.strip(),
                            "sixes": stats[3].text.strip(),
                            "sr": stats[4].text.strip()
                        })
                elif player_name and "bowling" in row.get_text().lower()[:10]:
                    stats = row.find_all("div", class_="cb-col cb-col-100 cb-scrd-itm")
                    if len(stats) >= 6:
                        bowlers.append({
                            "name": player_name.text.strip(),
                            "overs": stats[0].text.strip(),
                            "maidens": stats[1].text.strip(),
                            "runs": stats[2].text.strip(),
                            "wickets": stats[3].text.strip(),
                            "noballs": stats[4].text.strip(),
                            "wides": stats[5].text.strip(),
                            "economy": stats[6].text.strip() if len(stats) > 6 else "N/A"
                        })
            match_info["scorecard"] = {"batting": batters, "bowling": bowlers}
        else:
            match_info["scorecard"] = {"batting": [], "bowling": []}
        
        # Squads
        squads_elems = soup.find_all("div", class_="cb-minfo-tm-nm") or soup.find_all("div", class_="cb-hmscg-bat-txt")
        teams = match_info["teams"].split("vs")
        match_info["squads"] = {
            "team1": [s.text.strip() for s in squads_elems[:11] if teams[0] in s.text] if squads_elems else [],
            "team2": [s.text.strip() for s in squads_elems[11:22] if len(teams) > 1 and teams[1] in s.text] if squads_elems and len(teams) > 1 else []
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