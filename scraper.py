import sys
import requests
from bs4 import BeautifulSoup
import json

def get_live_matches():
    url = "https://www.cricbuzz.com/cricket-match/live-scores"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        match_blocks = soup.find_all("div", class_="cb-mtch-lst cb-col cb-col-100 cb-tms-itm")
        matches = []
        
        for block in match_blocks:
            match_info = {}
            link = block.find("a", class_="text-hvr-underline")
            if link and "href" in link.attrs:
                match_info["matchId"] = link["href"].split("/")[-2]
            teams = block.find("h3", class_="cb-lv-scr-mtch-hdr")
            if teams:
                match_info["teams"] = teams.text.strip()
            score = block.find("div", class_="cb-lv-scrs-col")
            if score:
                match_info["score"] = score.text.strip()
            status = block.find("div", class_="cb-text-live") or block.find("div", class_="cb-text-complete")
            if status:
                match_info["status"] = status.text.strip()
            if match_info.get("matchId"):
                matches.append(match_info)
        return matches
    except Exception as e:
        print(f"Error scraping live matches: {e}", file=sys.stderr)
        return []

def get_match_details(match_id):
    url = f"https://www.cricbuzz.com/live-cricket-scores/{match_id}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        
        match_info = {"matchId": match_id}
        score = soup.find("div", class_="cb-min-bat-rw")
        if score:
            match_info["score"] = score.text.strip()
        teams = soup.find("h1", class_="cb-nav-hdr")
        if teams:
            match_info["teams"] = teams.text.strip().replace(" - Live Cricket Score", "")
        commentary = soup.find_all("div", class_="cb-com-ln")
        if commentary:
            match_info["commentary"] = [comm.text.strip() for comm in commentary[:5]]
        return match_info
    except Exception as e:
        print(f"Error scraping match {match_id}: {e}", file=sys.stderr)
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