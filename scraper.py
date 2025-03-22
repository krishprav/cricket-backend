# scraper.py (improved)
import requests
from bs4 import BeautifulSoup
import json
import sys
import logging
from urllib.parse import urljoin

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BASE_URL = "https://www.cricbuzz.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}

def get_live_matches():
    """Fetch live matches with improved parsing"""
    try:
        response = requests.get(f"{BASE_URL}/cricket-match/live-scores", headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')
        
        matches = []
        seen_ids = set()
        
        for card in soup.find_all('div', class_='cb-mtch-lst'):
            match_link = card.find('a', class_='text-hvr-underline')
            if not match_link:
                continue

            match_id = match_link['href'].split('/')[-2]
            if match_id in seen_ids:
                continue
            seen_ids.add(match_id)

            teams = match_link.find('h3').text.strip()
            status_div = card.find('div', class_='cb-font-12')
            status = status_div.text.strip() if status_div else 'In Progress'
            
            score_div = card.find('div', class_='cb-scr-wll-chrct')
            score = score_div.text.strip() if score_div else 'Match starting soon'
            
            matches.append({
                "matchId": match_id,
                "teams": teams,
                "score": score,
                "status": status,
                "url": urljoin(BASE_URL, match_link['href'])
            })

        return matches if matches else [{"error": "No live matches found"}]
    
    except Exception as e:
        logger.error(f"Error fetching live matches: {str(e)}")
        return [{"error": "Failed to fetch live matches"}]

def get_match_details(match_id):
    """Get detailed match data with enhanced parsing"""
    try:
        url = f"{BASE_URL}/live-cricket-scores/{match_id}"
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')

        # Extract main match info
        main_info = soup.find('div', class_='cb-col cb-col-100 cb-min-stts')
        teams = main_info.find('h1').text.strip() if main_info else "Teams Not Found"
        
        # Score extraction
        score_block = soup.find('div', class_='cb-min-bat-rw')
        score = score_block.text.strip() if score_block else "Score Not Available"
        
        # Detailed stats
        stats = {
            'batting': [],
            'bowling': [],
            'extras': [],
            'fall_of_wickets': []
        }

        # Batting and bowling tables
        for table in soup.find_all('div', class_='cb-col cb-col-100 cb-ltst-wgt-hdr'):
            header = table.find('div', class_='cb-col cb-col-100 cb-scrd-hdr-rw')
            if not header:
                continue
            
            if 'BATTERS' in header.text:
                for row in table.find_all('div', class_='cb-col cb-col-100 cb-scrd-itms'):
                    cols = row.find_all('div', recursive=False)
                    if len(cols) >= 7:
                        stats['batting'].append({
                            'name': cols[0].text.strip(),
                            'runs': cols[2].text.strip(),
                            'balls': cols[3].text.strip(),
                            '4s': cols[4].text.strip(),
                            '6s': cols[5].text.strip(),
                            'sr': cols[6].text.strip()
                        })
            
            elif 'BOWLERS' in header.text:
                for row in table.find_all('div', class_='cb-col cb-col-100 cb-scrd-itms'):
                    cols = row.find_all('div', recursive=False)
                    if len(cols) >= 8:
                        stats['bowling'].append({
                            'name': cols[0].text.strip(),
                            'overs': cols[2].text.strip(),
                            'maidens': cols[3].text.strip(),
                            'runs': cols[4].text.strip(),
                            'wickets': cols[5].text.strip(),
                            'economy': cols[7].text.strip()
                        })

        # Additional match info
        match_data = {
            'matchId': match_id,
            'teams': teams,
            'score': score,
            'status': soup.find('div', class_='cb-text-inprogress') or 
                     soup.find('div', class_='cb-text-complete'),
            'stats': stats,
            'partnership': soup.find('span', class_='cb-min-itm-rw').text.strip() if soup.find('span', class_='cb-min-itm-rw') else '',
            'last_wicket': soup.find('span', class_='cb-ovr-num').text.strip() if soup.find('span', class_='cb-ovr-num') else '',
            'current_batters': [b.text.strip() for b in soup.find_all('div', class_='cb-col cb-col-50')[::2]],
            'current_bowlers': [b.text.strip() for b in soup.find_all('div', class_='cb-col cb-col-50')[1::2]]
        }

        return match_data

    except Exception as e:
        logger.error(f"Error fetching match {match_id}: {str(e)}")
        return {"error": "Failed to fetch match details"}

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "list":
        print(json.dumps(get_match_details(sys.argv[1])))
    else:
        print(json.dumps(get_live_matches())))
