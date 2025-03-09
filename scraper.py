import sys
import requests
from bs4 import BeautifulSoup
import json
import time
import re

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
            
            # Add match type and series info
            series_info = block.find("div", class_="cb-mtch-lst-itm-sm")
            if series_info:
                match_info["series"] = series_info.text.strip()
            
            # Add timestamp
            match_info["timestamp"] = int(time.time())
            
            if match_info.get("matchId"):
                matches.append(match_info)
        return matches
    except Exception as e:
        print(f"Error scraping live matches: {e}", file=sys.stderr)
        return []

def try_api_endpoint(match_id, endpoint_type="commentary"):
    """Attempt to get data from Cricbuzz API endpoints"""
    endpoints = {
        "commentary": f"https://www.cricbuzz.com/api/cricket-match/commentary/{match_id}",
        "scorecard": f"https://www.cricbuzz.com/api/cricket-match/scorecard/{match_id}",
        "mini": f"https://www.cricbuzz.com/api/cricket-match/mini-commentary/{match_id}"
    }
    
    url = endpoints.get(endpoint_type)
    if not url:
        return None
        
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            content_type = response.headers.get('Content-Type', '')
            if 'application/json' in content_type:
                return response.json()
        return None
    except Exception as e:
        print(f"API request failed for {endpoint_type}: {e}", file=sys.stderr)
        return None

def get_match_details(match_id):
    # First try the API endpoints
    api_data = try_api_endpoint(match_id, "mini")
    if api_data:
        print(f"Successfully fetched API data for match {match_id}", file=sys.stderr)
        return api_data
    
    # Fall back to HTML scraping if API fails
    url = f"https://www.cricbuzz.com/live-cricket-scores/{match_id}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        
        match_info = {
            "matchId": match_id,
            "timestamp": int(time.time())
        }
        
        # Basic match info
        score = soup.find("div", class_="cb-min-bat-rw")
        if score:
            match_info["score"] = score.text.strip()
            # Detect events
            score_text = score.text.lower()
            if '6' in score_text:
                match_info["event"] = "six"
            elif '4' in score_text:
                match_info["event"] = "four"
            elif '50' in score_text:
                match_info["event"] = "fifty"
            elif '100' in score_text:
                match_info["event"] = "hundred"
            elif 'wicket' in score_text or 'out' in score_text:
                match_info["event"] = "wicket"
        
        # Match title and teams
        teams = soup.find("h1", class_="cb-nav-hdr")
        if teams:
            title_text = teams.text.strip().replace(" - Live Cricket Score", "")
            match_info["title"] = title_text
            
            # Try to extract team names
            team_pattern = re.compile(r'(.+)\s+vs\s+(.+)')
            match = team_pattern.search(title_text)
            if match:
                match_info["teams"] = {
                    "team1": match.group(1).strip(),
                    "team2": match.group(2).strip()
                }
            else:
                match_info["teams"] = title_text
        
        # Match status
        status = soup.find("div", class_="cb-text-live") or soup.find("div", class_="cb-text-complete")
        if status:
            match_info["status"] = status.text.strip()
        
        # Match venue and details
        venue_info = soup.find("div", class_="cb-nav-subhdr cb-font-12")
        if venue_info:
            match_info["venue"] = venue_info.text.strip()
        
        # Commentary
        commentary_data = []
        commentary = soup.find_all("div", class_="cb-com-ln")
        for comm in commentary:
            over_info = comm.find_previous("div", class_="cb-com-over")
            comm_text = comm.text.strip()
            
            # Extract event type from commentary
            event_type = "regular"
            if any(word in comm_text.lower() for word in ["six", "sixer"]):
                event_type = "six"
            elif any(word in comm_text.lower() for word in ["four", "boundary"]):
                event_type = "four"
            elif any(word in comm_text.lower() for word in ["out", "wicket", "bowled", "lbw", "caught"]):
                event_type = "wicket"
            
            commentary_entry = {
                "text": comm_text,
                "over": over_info.text.strip() if over_info else "",
                "type": event_type
            }
            commentary_data.append(commentary_entry)
        
        if commentary_data:
            match_info["commentary"] = commentary_data
        
        # Detailed scorecard (expanded)
        batting_stats = []
        bowling_stats = []
        
        # Batting stats
        batting_tables = soup.find_all("div", class_="cb-col cb-col-100 cb-ltst-wgt-hdr")
        for table in batting_tables:
            team_name_elem = table.find("div", class_="cb-scrd-hdr-rw")
            team_name = team_name_elem.text.strip() if team_name_elem else "Unknown Team"
            
            batsmen = table.find_all("div", class_="cb-scrd-itms")
            for batsman in batsmen:
                cols = batsman.find_all("div", class_="cb-col")
                if len(cols) >= 7:  # Basic check for batsman row
                    try:
                        name_elem = cols[0]
                        status_elem = cols[1]
                        
                        # Skip header rows
                        if "BATSMAN" in name_elem.text:
                            continue
                            
                        batsman_data = {
                            "team": team_name,
                            "name": name_elem.text.strip(),
                            "status": status_elem.text.strip(),
                            "runs": cols[2].text.strip(),
                            "balls": cols[3].text.strip(),
                            "fours": cols[5].text.strip(),
                            "sixes": cols[6].text.strip(),
                            "strikeRate": cols[7].text.strip() if len(cols) > 7 else "0.0"
                        }
                        batting_stats.append(batsman_data)
                    except Exception as e:
                        print(f"Error parsing batsman: {e}", file=sys.stderr)
        
        # Bowling stats
        bowling_tables = soup.find_all("div", class_="cb-col cb-col-100 cb-ltst-wgt-hdr")
        for table in bowling_tables:
            bowling_header = table.find("div", class_="cb-scrd-hdr-rw", text=lambda t: t and "BOWLING" in t)
            if bowling_header:
                team_name = bowling_header.text.strip().replace("BOWLING", "").strip()
                
                bowlers = table.find_all("div", class_="cb-scrd-itms")
                for bowler in bowlers:
                    cols = bowler.find_all("div", class_="cb-col")
                    if len(cols) >= 8:  # Basic check for bowler row
                        try:
                            name_elem = cols[0]
                            
                            # Skip header rows
                            if "BOWLER" in name_elem.text:
                                continue
                                
                            bowler_data = {
                                "team": team_name,
                                "name": name_elem.text.strip(),
                                "overs": cols[1].text.strip(),
                                "maidens": cols[2].text.strip(),
                                "runs": cols[3].text.strip(),
                                "wickets": cols[4].text.strip(),
                                "economy": cols[5].text.strip(),
                                "dots": cols[6].text.strip() if len(cols) > 6 else "0",
                                "fours": cols[7].text.strip() if len(cols) > 7 else "0",
                                "sixes": cols[8].text.strip() if len(cols) > 8 else "0"
                            }
                            bowling_stats.append(bowler_data)
                        except Exception as e:
                            print(f"Error parsing bowler: {e}", file=sys.stderr)
        
        if batting_stats:
            match_info["battingStats"] = batting_stats
        
        if bowling_stats:
            match_info["bowlingStats"] = bowling_stats
        
        # Current partnership (if available)
        partnership = soup.find("span", class_="cb-font-20 text-bold")
        if partnership:
            match_info["currentPartnership"] = partnership.text.strip()
        
        # Recent overs
        recent_overs_div = soup.find("div", class_="cb-col-100 cb-col cb-scrd-sub-hdr cb-bg-gray")
        if recent_overs_div and "Recent Overs" in recent_overs_div.text:
            overs_div = recent_overs_div.find_next("div", class_="cb-col-100 cb-col")
            if overs_div:
                match_info["recentOvers"] = overs_div.text.strip()
        
        # Points Table (fetch from tournament page if available)
        match_info["pointsTable"] = {"note": "Fetch from tournament page in future"}
        
        # Squads (from playing XI section)
        squads = {}
        playing_xi_section = soup.find("div", class_="cb-col-100 cb-col cb-com-ln cb-col-rt", string=lambda t: t and "Playing XI" in t)
        if playing_xi_section:
            team_sections = playing_xi_section.find_next_siblings("div", class_="cb-col-100 cb-col cb-com-ln")
            current_team = None
            for section in team_sections:
                text = section.text.strip()
                if ":" in text:  # Team header
                    current_team = text.split(":")[0].strip()
                    squads[current_team] = []
                elif current_team:  # Player
                    squads[current_team].append(text)
        
        if squads:
            match_info["squads"] = squads
        
        # Match stage and format
        format_info = soup.find("div", class_="cb-nav-subhdr cb-font-12")
        if format_info:
            format_text = format_info.text.lower()
            if "test" in format_text:
                match_info["format"] = "Test"
            elif "odi" in format_text:
                match_info["format"] = "ODI"
            elif "t20" in format_text:
                match_info["format"] = "T20"
            
            # Extract series/tournament info
            series_match = re.search(r'(.+?),\s+\d', format_text)
            if series_match:
                match_info["series"] = series_match.group(1).strip()
        
        return match_info
    except Exception as e:
        print(f"Error scraping match {match_id}: {e}", file=sys.stderr)
        return {"error": str(e), "matchId": match_id}

def get_detailed_commentary(match_id):
    """Get detailed ball-by-ball commentary"""
    url = f"https://www.cricbuzz.com/cricket-full-commentary/{match_id}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        # First try the API endpoint
        api_data = try_api_endpoint(match_id, "commentary")
        if api_data:
            return {"matchId": match_id, "commentary": api_data}
        
        # Fall back to HTML scraping
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        
        commentary_blocks = soup.find_all("div", class_="cb-col-100 cb-col cb-com-ln")
        commentary_data = []
        
        for block in commentary_blocks:
            over_info = block.find_previous("div", class_="cb-col-100 cb-col cb-com-over")
            over_text = over_info.text.strip() if over_info else ""
            
            comm_text = block.text.strip()
            
            # Skip empty or irrelevant entries
            if not comm_text or len(comm_text) < 3:
                continue
                
            # Categorize commentary
            event_type = "regular"
            if any(word in comm_text.lower() for word in ["six", "sixer"]):
                event_type = "six"
            elif any(word in comm_text.lower() for word in ["four", "boundary"]):
                event_type = "four"
            elif any(word in comm_text.lower() for word in ["out", "wicket", "bowled", "lbw", "caught"]):
                event_type = "wicket"
                
            commentary_entry = {
                "text": comm_text,
                "over": over_text,
                "type": event_type,
                "timestamp": int(time.time())
            }
            commentary_data.append(commentary_entry)
            
        return {"matchId": match_id, "commentary": commentary_data}
    except Exception as e:
        print(f"Error scraping detailed commentary for match {match_id}: {e}", file=sys.stderr)
        return {"matchId": match_id, "error": str(e)}

def get_points_table(tournament_id=None):
    """Get tournament points table"""
    if not tournament_id:
        # Try to find active tournaments
        url = "https://www.cricbuzz.com/cricket-schedule/series"
    else:
        url = f"https://www.cricbuzz.com/cricket-series/{tournament_id}/points-table"
        
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        
        points_tables = []
        
        # Find all points table blocks
        table_blocks = soup.find_all("div", class_="cb-col-100 cb-col cb-sr-hdr-main")
        for block in table_blocks:
            table_name = block.find("div", class_="cb-col-100 cb-col cb-sr-hdr")
            table_name_text = table_name.text.strip() if table_name else "Points Table"
            
            table_data = []
            team_rows = block.find_all("div", class_="cb-col-100 cb-col cb-sr-main")
            for row in team_rows:
                cols = row.find_all("div", class_="cb-col")
                if len(cols) >= 5:
                    team_data = {
                        "position": cols[0].text.strip(),
                        "team": cols[1].text.strip(),
                        "matches": cols[2].text.strip(),
                        "won": cols[3].text.strip(),
                        "lost": cols[4].text.strip(),
                        "points": cols[-2].text.strip() if len(cols) > 5 else "0",
                        "nrr": cols[-1].text.strip() if len(cols) > 6 else "0.000"
                    }
                    table_data.append(team_data)
            
            if table_data:
                points_tables.append({
                    "name": table_name_text,
                    "teams": table_data
                })
        
        return {"pointsTables": points_tables}
    except Exception as e:
        print(f"Error fetching points table: {e}", file=sys.stderr)
        return {"error": str(e)}

def get_player_stats(player_id):
    """Get player statistics"""
    url = f"https://www.cricbuzz.com/profiles/{player_id}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        
        player_info = {"playerId": player_id}
        
        # Basic player info
        name = soup.find("h1", class_="cb-font-40")
        if name:
            player_info["name"] = name.text.strip()
        
        profile_text = soup.find("div", class_="cb-col-60 cb-col cb-col-rt")
        if profile_text:
            player_info["profile"] = profile_text.text.strip()
        
        # Player stats tables
        stats_tables = soup.find_all("div", class_="cb-col cb-col-100 cb-plyr-tbl")
        batting_stats = {}
        bowling_stats = {}
        
        for table in stats_tables:
            header = table.find("div", class_="cb-col cb-col-100 cb-scrd-hdr-rw")
            if not header:
                continue
                
            header_text = header.text.strip()
            
            if "BATTING" in header_text:
                format_match = re.search(r'BATTING\s+&\s+FIELDING\s+(\w+)', header_text)
                format_type = format_match.group(1) if format_match else "Overall"
                
                rows = table.find_all("div", class_="cb-col cb-col-100 cb-scrd-itms")
                format_stats = {}
                
                for row in rows:
                    cols = row.find_all("div", class_="cb-col")
                    if len(cols) >= 7:
                        stat_type = cols[0].text.strip()
                        format_stats[stat_type] = {
                            "matches": cols[1].text.strip(),
                            "innings": cols[2].text.strip(),
                            "runs": cols[3].text.strip(),
                            "highestScore": cols[4].text.strip(),
                            "average": cols[5].text.strip(),
                            "strikeRate": cols[6].text.strip(),
                            "hundreds": cols[7].text.strip() if len(cols) > 7 else "0",
                            "fifties": cols[8].text.strip() if len(cols) > 8 else "0"
                        }
                
                if format_stats:
                    batting_stats[format_type] = format_stats
            
            elif "BOWLING" in header_text:
                format_match = re.search(r'BOWLING\s+(\w+)', header_text)
                format_type = format_match.group(1) if format_match else "Overall"
                
                rows = table.find_all("div", class_="cb-col cb-col-100 cb-scrd-itms")
                format_stats = {}
                
                for row in rows:
                    cols = row.find_all("div", class_="cb-col")
                    if len(cols) >= 7:
                        stat_type = cols[0].text.strip()
                        format_stats[stat_type] = {
                            "matches": cols[1].text.strip(),
                            "innings": cols[2].text.strip(),
                            "overs": cols[3].text.strip(),
                            "runs": cols[4].text.strip(),
                            "wickets": cols[5].text.strip(),
                            "bestInnings": cols[6].text.strip(),
                            "average": cols[7].text.strip() if len(cols) > 7 else "0",
                            "economy": cols[8].text.strip() if len(cols) > 8 else "0"
                        }
                
                if format_stats:
                    bowling_stats[format_type] = format_stats
        
        if batting_stats:
            player_info["battingStats"] = batting_stats
        
        if bowling_stats:
            player_info["bowlingStats"] = bowling_stats
        
        return player_info
    except Exception as e:
        print(f"Error fetching player stats for player {player_id}: {e}", file=sys.stderr)
        return {"error": str(e), "playerId": player_id}

if __name__ == "__main__":
    if len(sys.argv) <= 1:
        print(json.dumps({"error": "No command provided"}))
        sys.exit(1)
        
    command = sys.argv[1]
    
    if command == "list":
        matches = get_live_matches()
        print(json.dumps(matches))
    elif command == "commentary" and len(sys.argv) > 2:
        match_id = sys.argv[2]
        data = get_detailed_commentary(match_id)
        print(json.dumps(data))
    elif command == "points" and len(sys.argv) > 2:
        tournament_id = sys.argv[2]
        data = get_points_table(tournament_id)
        print(json.dumps(data))
    elif command == "player" and len(sys.argv) > 2:
        player_id = sys.argv[2]
        data = get_player_stats(player_id)
        print(json.dumps(data))
    elif command.isdigit():  # Assume it's a match ID
        data = get_match_details(command)
        if data:
            print(json.dumps(data))
        else:
            print(json.dumps({"error": "Failed to fetch match data"}))
    else:
        print(json.dumps({"error": "Invalid command"}))
