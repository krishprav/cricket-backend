import requests
import pandas as pd
from bs4 import BeautifulSoup
import json
import time
import os
import logging
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("cricket_scraper.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("cricket_scraper")

class CricketScraper:
    def __init__(self, base_url="https://www.cricbuzz.com", output_dir="data"):
        self.base_url = base_url
        self.output_dir = output_dir
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://www.cricbuzz.com/'
        }
        
        # Create output directory if it doesn't exist
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
    
    def fetch_page(self, url):
        """Fetch HTML content from a URL with retries"""
        max_retries = 3
        retry_delay = 2  # seconds
        
        for attempt in range(max_retries):
            try:
                response = requests.get(url, headers=self.headers)
                response.raise_for_status()
                return response.text
            except requests.exceptions.RequestException as e:
                logger.error(f"Error fetching {url}: {e}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error(f"Failed to fetch {url} after {max_retries} attempts")
                    raise
    
    def get_live_matches(self):
        """Get all live matches"""
        logger.info("Fetching live matches")
        url = f"{self.base_url}/cricket-match/live-scores"
        html = self.fetch_page(url)
        soup = BeautifulSoup(html, 'html.parser')
        matches = []
        
        # Find all live match elements
        for match_element in soup.select('.cb-mtch-lst .cb-col-100.cb-col'):
            try:
                match_link = match_element.select_one('a')['href']
                match_id = match_link.split('/')[-1]
                match_title = match_element.select_one('.cb-lv-scr-mtch-hdr').text.strip()
                status_text = match_element.select_one('.cb-lv-scr-mtchs-tm').text.strip()
                
                team_elements = match_element.select('.cb-hmscg-tm-nm')
                score_elements = match_element.select('.cb-hmscg-tm-nm+.cb-ovs')
                
                # Only include current live matches
                if 'Live' in status_text or 'In Progress' in status_text:
                    match_data = {
                        'id': match_id,
                        'title': match_title,
                        'status': status_text,
                        'team1': {
                            'name': team_elements[0].text.strip() if len(team_elements) > 0 else 'Team 1',
                            'score': score_elements[0].text.strip() if len(score_elements) > 0 else ''
                        },
                        'team2': {
                            'name': team_elements[1].text.strip() if len(team_elements) > 1 else 'Team 2',
                            'score': score_elements[1].text.strip() if len(score_elements) > 1 else ''
                        },
                        'url': f"{self.base_url}{match_link}"
                    }
                    matches.append(match_data)
            except Exception as e:
                logger.error(f"Error parsing match element: {e}")
        
        # Save to JSON file
        self._save_to_json(matches, "live_matches.json")
        logger.info(f"Found {len(matches)} live matches")
        return matches
    
    def get_match_details(self, match_id):
        """Get details for a specific match"""
        logger.info(f"Fetching details for match {match_id}")
        url = f"{self.base_url}/live-cricket-scorecard/{match_id}"
        html = self.fetch_page(url)
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract basic match info
        match_title = soup.select_one('.cb-nav-hdr .cb-nav-hdr-lg').text.strip() if soup.select_one('.cb-nav-hdr .cb-nav-hdr-lg') else 'Match'
        match_status = soup.select_one('.cb-mscr-item .cb-text-complete').text.strip() if soup.select_one('.cb-mscr-item .cb-text-complete') else 'In Progress'
        venue = soup.select_one('.cb-nav-subhdr .cb-font-12').text.strip() if soup.select_one('.cb-nav-subhdr .cb-font-12') else ''
        series = soup.select_one('.cb-nav-hdr .cb-nav-hdr-lg')['title'] if soup.select_one('.cb-nav-hdr .cb-nav-hdr-lg') else ''
        
        # Extract teams info
        teams = []
        for team_element in soup.select('.cb-mscr-tm'):
            team_name = team_element.select_one('.cb-mscr-tm-nm').text.strip() if team_element.select_one('.cb-mscr-tm-nm') else 'Team'
            team_score = team_element.select_one('.cb-mscr-tm-scr').text.strip() if team_element.select_one('.cb-mscr-tm-scr') else ''
            teams.append({'name': team_name, 'score': team_score})
        
        # Extract innings data
        innings = []
        for innings_header in soup.select('.cb-ltst-wgt-hdr'):
            innings_title = innings_header.select_one('.cb-scrd-hdr-rw h2')
            if not innings_title or 'Innings' not in innings_title.text:
                continue
            
            team_name = innings_title.text.split('Innings')[0].strip()
            score_element = innings_title.select_one('.pull-right')
            score = score_element.text.strip() if score_element else ''
            
            # Parse score for wickets and overs
            wickets = 0
            overs = ''
            if score:
                score_match = score.split('/')
                if len(score_match) > 1 and '(' in score:
                    wickets = int(score_match[1].split('(')[0].strip())
                    overs_match = score.split('(')[1].split('Ov')[0].strip()
                    overs = overs_match
            
            # Extract batsmen data
            batsmen = []
            for batsman_row in innings_header.select('.cb-scrd-itms .cb-col-100.cb-scrd-itm.cb-col-rt'):
                cols = batsman_row.select('.cb-col')
                if len(cols) < 7 or cols[0].text.strip() == 'BATSMEN':
                    continue
                
                batsman = {
                    'name': cols[0].text.strip(),
                    'dismissal': cols[1].text.strip(),
                    'runs': cols[2].text.strip(),
                    'balls': cols[3].text.strip(),
                    'fours': cols[4].text.strip(),
                    'sixes': cols[5].text.strip(),
                    'strikeRate': cols[6].text.strip()
                }
                batsmen.append(batsman)
            
            # Extract bowlers data
            bowlers = []
            bowling_table = innings_header.find_next_sibling('.cb-ltst-wgt-hdr')
            if bowling_table:
                for bowler_row in bowling_table.select('.cb-scrd-itms .cb-col-100.cb-scrd-itm.cb-col-rt'):
                    cols = bowler_row.select('.cb-col')
                    if len(cols) < 8 or cols[0].text.strip() == 'BOWLER':
                        continue
                    
                    bowler = {
                        'name': cols[0].text.strip(),
                        'overs': cols[1].text.strip(),
                        'maidens': cols[2].text.strip(),
                        'runs': cols[3].text.strip(),
                        'wickets': cols[4].text.strip(),
                        'noBalls': cols[5].text.strip(),
                        'wides': cols[6].text.strip(),
                        'economy': cols[7].text.strip()
                    }
                    bowlers.append(bowler)
            
            # Extract extras and fall of wickets
            extras = {'total': 0, 'byes': 0, 'legByes': 0, 'wides': 0, 'noBalls': 0, 'penalty': 0}
            extras_element = innings_header.select('.cb-scrd-itms .cb-col-100.cb-scrd-itm')[-2] if len(innings_header.select('.cb-scrd-itms .cb-col-100.cb-scrd-itm')) >= 2 else None
            if extras_element and 'Extras' in extras_element.text:
                extras_text = extras_element.text.strip()
                extras_match = extras_text.split('Extras')
                if len(extras_match) > 1:
                    try:
                        extras_values = extras_match[1].strip()
                        extras['total'] = int(extras_values.split('(')[0].strip())
                        extras_types = extras_values.split('(')[1].split(')')[0].split(',')
                        for extra_type in extras_types:
                            parts = extra_type.strip().split(' ')
                            if len(parts) == 2:
                                value, key = parts
                                if key == 'b':
                                    extras['byes'] = int(value)
                                elif key == 'lb':
                                    extras['legByes'] = int(value)
                                elif key == 'w':
                                    extras['wides'] = int(value)
                                elif key == 'nb':
                                    extras['noBalls'] = int(value)
                                elif key == 'p':
                                    extras['penalty'] = int(value)
                    except Exception as e:
                        logger.warning(f"Error parsing extras: {e}")
            
            # Extract fall of wickets
            fow_element = innings_header.select('.cb-col-100.cb-col.cb-scrd-itm')[-1] if innings_header.select('.cb-col-100.cb-col.cb-scrd-itm') else None
            fow_text = fow_element.text.strip() if fow_element else ''
            
            innings_data = {
                'team': {'name': team_name},
                'score': score,
                'wickets': wickets,
                'overs': overs,
                'batsmen': batsmen,
                'bowlers': bowlers,
                'extras': extras,
                'fallOfWickets': fow_text
            }
            innings.append(innings_data)
        
        # Construct final match details object
        match_details = {
            'id': match_id,
            'title': match_title,
            'status': match_status,
            'venue': venue,
            'series': series,
            'team1': teams[0] if len(teams) > 0 else {'name': 'Team 1', 'score': ''},
            'team2': teams[1] if len(teams) > 1 else {'name': 'Team 2', 'score': ''},
            'innings': innings
        }
        
        # Save to JSON file
        self._save_to_json(match_details, f"match_{match_id}.json")
        return match_details
    
    def get_match_commentary(self, match_id):
        """Get live commentary for a match"""
        logger.info(f"Fetching commentary for match {match_id}")
        url = f"{self.base_url}/live-cricket-scores/{match_id}"
        html = self.fetch_page(url)
        soup = BeautifulSoup(html, 'html.parser')
        
        commentary = []
        for comment_element in soup.select('.cb-com-ln'):
            text = comment_element.text.strip()
            over_element = comment_element.find_previous('.cb-com-over')
            over = over_element.text.strip() if over_element else ''
            timestamp = datetime.now().isoformat()
            
            # Detect wickets and boundaries
            is_wicket = 'OUT' in text or 'WICKET' in text
            is_boundary = 'FOUR' in text or 'SIX' in text
            is_four = 'FOUR' in text
            
            commentary.append({
                'text': text,
                'over': over,
                'timestamp': timestamp,
                'isWicket': is_wicket,
                'isBoundary': is_boundary,
                'isFour': is_boundary and is_four,
                'isSix': is_boundary and not is_four
            })
        
        # Reverse to get most recent first
        commentary.reverse()
        
        # Save to JSON file
        self._save_to_json(commentary, f"commentary_{match_id}.json")
        logger.info(f"Found {len(commentary)} commentary items")
        return commentary
    
    def get_points_table(self, series_id):
        """Get points table for a series"""
        logger.info(f"Fetching points table for series {series_id}")
        url = f"{self.base_url}/cricket-series/{series_id}/points-table"
        html = self.fetch_page(url)
        soup = BeautifulSoup(html, 'html.parser')
        
        points_table = []
        for table in soup.select('.cb-srs-pnts'):
            rows = table.select('tr')
            # Skip header row
            for row in rows[1:]:
                cols = row.select('td')
                if len(cols) < 9:
                    continue
                
                try:
                    team_data = {
                        'position': cols[0].text.strip(),
                        'team': cols[1].text.strip(),
                        'matches': int(cols[2].text.strip()),
                        'won': int(cols[3].text.strip()),
                        'lost': int(cols[4].text.strip()),
                        'tied': int(cols[5].text.strip()),
                        'noResult': int(cols[6].text.strip()),
                        'points': int(cols[7].text.strip()),
                        'netRunRate': float(cols[8].text.strip())
                    }
                    points_table.append(team_data)
                except (ValueError, IndexError) as e:
                    logger.warning(f"Error parsing points table row: {e}")
        
        # Save to JSON file
        self._save_to_json(points_table, f"points_table_{series_id}.json")
        return points_table
    
    def get_match_highlights(self, match_id):
        """Get key moments/highlights from a match"""
        logger.info(f"Fetching highlights for match {match_id}")
        url = f"{self.base_url}/cricket-match/live-scores/{match_id}"
        html = self.fetch_page(url)
        soup = BeautifulSoup(html, 'html.parser')
        
        highlights = []
        for highlight_element in soup.select('.cb-mat-key-evt'):
            text = highlight_element.text.strip()
            timestamp_element = highlight_element.select_one('.cb-mat-key-evt-time')
            timestamp = timestamp_element.text.strip() if timestamp_element else ''
            
            highlight_type = 'other'
            if 'FOUR' in text or 'SIX' in text:
                highlight_type = 'boundary'
            elif 'WICKET' in text:
                highlight_type = 'wicket'
            
            highlights.append({
                'text': text.replace(timestamp, '').strip() if timestamp else text,
                'timestamp': timestamp,
                'type': highlight_type
            })
        
        # Save to JSON file
        self._save_to_json(highlights, f"highlights_{match_id}.json")
        logger.info(f"Found {len(highlights)} highlights")
        return highlights
    
    def _save_to_json(self, data, filename):
        """Save data to JSON file"""
        filepath = os.path.join(self.output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved data to {filepath}")
    
    def update_all_data(self, series_id=None):
        """Update all data for live matches and optionally a series points table"""
        logger.info("Starting complete data update")
        start_time = time.time()
        
        # Get all live matches
        live_matches = self.get_live_matches()
        
        # Get details for each live match
        for match in live_matches:
            match_id = match['id']
            self.get_match_details(match_id)
            self.get_match_commentary(match_id)
            self.get_match_highlights(match_id)
            # Add a small delay to avoid overwhelming the server
            time.sleep(2)
        
        # Get points table if series ID is provided
        if series_id:
            self.get_points_table(series_id)
        
        elapsed_time = time.time() - start_time
        logger.info(f"Completed data update in {elapsed_time:.2f} seconds")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Cricket data scraper')
    parser.add_argument('--output', default='data', help='Output directory for JSON files')
    parser.add_argument('--match', help='Get data for specific match ID')
    parser.add_argument('--series', help='Get points table for specific series ID')
    parser.add_argument('--interval', type=int, default=60, help='Update interval in seconds (for continuous mode)')
    parser.add_argument('--continuous', action='store_true', help='Run in continuous update mode')
    
    args = parser.parse_args()
    
    scraper = CricketScraper(output_dir=args.output)
    
    if args.match:
        # Get data for specific match only
        match_id = args.match
        scraper.get_match_details(match_id)
        scraper.get_match_commentary(match_id)
        scraper.get_match_highlights(match_id)
    elif args.series:
        # Get points table for specific series
        scraper.get_points_table(args.series)
    elif args.continuous:
        # Run in continuous mode with specified interval
        logger.info(f"Running in continuous mode with {args.interval} second intervals")
        try:
            while True:
                scraper.update_all_data(args.series)
                logger.info(f"Sleeping for {args.interval} seconds...")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            logger.info("Stopped by user")
    else:
        # Just do a one-time update of all data
        scraper.update_all_data(args.series)
