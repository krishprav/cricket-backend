const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const morgan = require('morgan');
const rateLimit = require('express-rate-limit');
const axios = require('axios');
const cheerio = require('cheerio');
const TensorFlow = require('@tensorflow/tfjs-node');

const app = express();
const PORT = process.env.PORT || 5000;

// Middleware
app.use(cors());
app.use(helmet());
app.use(morgan('dev'));
app.use(express.json());

// Rate limiting
const limiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 100, // limit each IP to 100 requests per windowMs
  standardHeaders: true,
  legacyHeaders: false,
});
app.use(limiter);

// Load ML model for match prediction
let predictionModel;
const loadModel = async () => {
  try {
    predictionModel = await TensorFlow.loadLayersModel('file://./models/cricket_prediction_model/model.json');
    console.log('Prediction model loaded successfully');
  } catch (error) {
    console.error('Error loading prediction model:', error);
  }
};
loadModel();

// Cricbuzz base URL
const CRICBUZZ_URL = 'https://www.cricbuzz.com';

// Utility function to get HTML content from Cricbuzz
async function fetchCricbuzzPage(url) {
  try {
    const response = await axios.get(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://www.cricbuzz.com/'
      }
    });
    return response.data;
  } catch (error) {
    console.error('Error fetching Cricbuzz page:', error);
    throw new Error('Failed to fetch data from Cricbuzz');
  }
}

// Routes
// Get all live matches
app.get('/api/matches/live', async (req, res) => {
  try {
    const html = await fetchCricbuzzPage(`${CRICBUZZ_URL}/cricket-match/live-scores`);
    const $ = cheerio.load(html);
    const matches = [];

    // Find all live match elements
    $('.cb-mtch-lst .cb-col-100.cb-col').each((i, element) => {
      const matchElement = $(element);
      
      // Extract match details
      const matchLink = matchElement.find('a').attr('href');
      const matchId = matchLink.split('/').pop();
      const matchTitle = matchElement.find('.cb-lv-scr-mtch-hdr').text().trim();
      const statusText = matchElement.find('.cb-lv-scr-mtchs-tm').text().trim();
      const team1Element = matchElement.find('.cb-hmscg-tm-nm').eq(0);
      const team2Element = matchElement.find('.cb-hmscg-tm-nm').eq(1);
      const team1Score = matchElement.find('.cb-hmscg-tm-nm+.cb-ovs').eq(0).text().trim();
      const team2Score = matchElement.find('.cb-hmscg-tm-nm+.cb-ovs').eq(1).text().trim();
      
      // Only include current live matches
      if (statusText.includes('Live') || statusText.includes('In Progress')) {
        matches.push({
          id: matchId,
          title: matchTitle,
          status: statusText,
          team1: {
            name: team1Element.text().trim(),
            score: team1Score
          },
          team2: {
            name: team2Element.text().trim(),
            score: team2Score
          },
          url: `${CRICBUZZ_URL}${matchLink}`
        });
      }
    });

    res.json(matches);
  } catch (error) {
    console.error('Error in /api/matches/live:', error);
    res.status(500).json({ error: 'Failed to fetch live matches' });
  }
});

// Get details for a specific match
app.get('/api/matches/:matchId', async (req, res) => {
  try {
    const { matchId } = req.params;
    const html = await fetchCricbuzzPage(`${CRICBUZZ_URL}/live-cricket-scorecard/${matchId}`);
    const $ = cheerio.load(html);
    
    // Extract basic match info
    const matchTitle = $('.cb-nav-hdr .cb-nav-hdr-lg').text().trim();
    const matchStatus = $('.cb-mscr-item .cb-text-complete').text().trim() || 'In Progress';
    const venue = $('.cb-nav-subhdr .cb-font-12').text().trim();
    const series = $('.cb-nav-hdr .cb-nav-hdr-lg').attr('title');
    
    // Extract teams info
    const teams = [];
    $('.cb-mscr-tm').each((i, element) => {
      const teamName = $(element).find('.cb-mscr-tm-nm').text().trim();
      const teamScore = $(element).find('.cb-mscr-tm-scr').text().trim();
      teams.push({ name: teamName, score: teamScore });
    });
    
    // Extract innings data (batting and bowling)
    const innings = [];
    $('.cb-ltst-wgt-hdr').each((inningsIndex, inningsElement) => {
      const inningsTitle = $(inningsElement).find('.cb-scrd-hdr-rw h2').text().trim();
      if (!inningsTitle.includes('Innings')) return;
      
      const teamName = inningsTitle.split('Innings')[0].trim();
      const score = $(inningsElement).find('.cb-scrd-hdr-rw h2 .pull-right').text().trim();
      
      const batsmen = [];
      $(inningsElement).find('.cb-scrd-itms .cb-col-100.cb-scrd-itm.cb-col-rt').each((i, batsmanRow) => {
        const name = $(batsmanRow).find('.cb-col.cb-col-25').text().trim();
        const dismissal = $(batsmanRow).find('.cb-col.cb-col-33').text().trim();
        const runs = $(batsmanRow).find('.cb-col.cb-col-8.text-right').eq(0).text().trim();
        const balls = $(batsmanRow).find('.cb-col.cb-col-8.text-right').eq(1).text().trim();
        const fours = $(batsmanRow).find('.cb-col.cb-col-8.text-right').eq(2).text().trim();
        const sixes = $(batsmanRow).find('.cb-col.cb-col-8.text-right').eq(3).text().trim();
        const strikeRate = $(batsmanRow).find('.cb-col.cb-col-8.text-right').eq(4).text().trim();
        
        if (name && name !== 'BATSMEN') {
          batsmen.push({
            name,
            dismissal,
            runs,
            balls,
            fours,
            sixes,
            strikeRate
          });
        }
      });
      
      // Extract bowling data
      const bowlers = [];
      const bowlingTable = $(inningsElement).next('.cb-ltst-wgt-hdr').find('.cb-scrd-itms');
      
      bowlingTable.find('.cb-scrd-itms .cb-col-100.cb-scrd-itm.cb-col-rt').each((i, bowlerRow) => {
        const name = $(bowlerRow).find('.cb-col.cb-col-40').text().trim();
        const overs = $(bowlerRow).find('.cb-col.cb-col-10.text-right').eq(0).text().trim();
        const maidens = $(bowlerRow).find('.cb-col.cb-col-10.text-right').eq(1).text().trim();
        const runs = $(bowlerRow).find('.cb-col.cb-col-10.text-right').eq(2).text().trim();
        const wickets = $(bowlerRow).find('.cb-col.cb-col-10.text-right').eq(3).text().trim();
        const noBalls = $(bowlerRow).find('.cb-col.cb-col-10.text-right').eq(4).text().trim();
        const wides = $(bowlerRow).find('.cb-col.cb-col-10.text-right').eq(5).text().trim();
        const economy = $(bowlerRow).find('.cb-col.cb-col-10.text-right').eq(6).text().trim();
        
        if (name && name !== 'BOWLER') {
          bowlers.push({
            name,
            overs,
            maidens,
            runs,
            wickets,
            noBalls,
            wides,
            economy
          });
        }
      });
      
      // Extract extras and fall of wickets
      const extrasText = $(inningsElement).find('.cb-scrd-itms .cb-col-100.cb-scrd-itm').eq(-2).text().trim();
      const fowText = $(inningsElement).find('.cb-col-100.cb-col.cb-scrd-itm').eq(-1).text().trim();
      
      // Parse extras
      const extras = {
        total: 0,
        byes: 0,
        legByes: 0,
        wides: 0,
        noBalls: 0,
        penalty: 0
      };
      
      if (extrasText.includes('Extras')) {
        const extrasMatch = extrasText.match(/Extras\s+(\d+)\s+\((.*)\)/);
        if (extrasMatch) {
          extras.total = parseInt(extrasMatch[1], 10);
          const extraTypes = extrasMatch[2].split(',');
          extraTypes.forEach(type => {
            const [value, key] = type.trim().split(' ');
            if (key === 'b') extras.byes = parseInt(value, 10);
            if (key === 'lb') extras.legByes = parseInt(value, 10);
            if (key === 'w') extras.wides = parseInt(value, 10);
            if (key === 'nb') extras.noBalls = parseInt(value, 10);
            if (key === 'p') extras.penalty = parseInt(value, 10);
          });
        }
      }
  
      // Extract match summary from score
      let wickets = 0;
      let overs = '';
      if (score) {
        const scoreMatch = score.match(/(\d+)\/(\d+)\s+\((\d+\.\d+)\s+Ov\)/);
        if (scoreMatch) {
          wickets = parseInt(scoreMatch[2], 10);
          overs = scoreMatch[3];
        }
      }
  
      innings.push({
        team: { name: teamName },
        score,
        wickets,
        overs,
        batsmen,
        bowlers,
        extras,
        fallOfWickets: fowText
      });
    });
  
    // Construct final match details object
    const matchDetails = {
      id: matchId,
      title: matchTitle,
      status: matchStatus,
      venue,
      series,
      team1: teams[0] || { name: 'Team 1', score: '' },
      team2: teams[1] || { name: 'Team 2', score: '' },
      innings
    };
  
    res.json(matchDetails);
  } catch (error) {
    console.error('Error in /api/matches/:matchId:', error);
    res.status(500).json({ error: 'Failed to fetch match details' });
  }
});

// Get live commentary for a match
app.get('/api/matches/:matchId/commentary', async (req, res) => {
  try {
    const { matchId } = req.params;
    const html = await fetchCricbuzzPage(`${CRICBUZZ_URL}/live-cricket-scores/${matchId}`);
    const $ = cheerio.load(html);
    
    const commentary = [];
    
    $('.cb-com-ln').each((i, element) => {
      const commentEl = $(element);
      const text = commentEl.text().trim();
      const overEl = commentEl.prev('.cb-com-over');
      const over = overEl.length ? overEl.text().trim() : '';
      const timestamp = new Date().toISOString();
      
      // Detect wickets and boundaries
      const isWicket = text.includes('OUT') || text.includes('WICKET');
      const isBoundary = text.includes('FOUR') || text.includes('SIX');
      const isFour = text.includes('FOUR');
      
      commentary.push({
        text,
        over,
        timestamp,
        isWicket,
        isBoundary,
        isFour: isBoundary && isFour,
        isSix: isBoundary && !isFour
      });
    });
    
    res.json(commentary.reverse());  // Most recent first
  } catch (error) {
    console.error('Error in /api/matches/:matchId/commentary:', error);
    res.status(500).json({ error: 'Failed to fetch match commentary' });
  }
});

// Get match prediction
app.get('/api/matches/:matchId/prediction', async (req, res) => {
  try {
    const { matchId } = req.params;
    
    // Fetch match details to get current state
    const matchDetailsUrl = `${CRICBUZZ_URL}/live-cricket-scorecard/${matchId}`;
    const html = await fetchCricbuzzPage(matchDetailsUrl);
    const $ = cheerio.load(html);
    
    // Extract teams
    const team1Name = $('.cb-mscr-tm').eq(0).find('.cb-mscr-tm-nm').text().trim();
    const team2Name = $('.cb-mscr-tm').eq(1).find('.cb-mscr-tm-nm').text().trim();
    
    // Extract score and overs
    const team1Score = $('.cb-mscr-tm').eq(0).find('.cb-mscr-tm-scr').text().trim();
    const team2Score = $('.cb-mscr-tm').eq(1).find('.cb-mscr-tm-scr').text().trim();
    
    // Parse the scores
    const parseScore = (scoreText) => {
      if (!scoreText) return { runs: 0, wickets: 0, overs: 0 };
      
      const scoreMatch = scoreText.match(/(\d+)\/(\d+)\s+\((\d+\.\d+)\s+Ov\)/);
      if (scoreMatch) {
        return {
          runs: parseInt(scoreMatch[1], 10),
          wickets: parseInt(scoreMatch[2], 10),
          overs: parseFloat(scoreMatch[3])
        };
      }
      return { runs: 0, wickets: 0, overs: 0 };
    };
    
    const team1Data = parseScore(team1Score);
    const team2Data = parseScore(team2Score);
    
    // Match state analysis
    const matchState = {
      team1: {
        name: team1Name,
        ...team1Data
      },
      team2: {
        name: team2Name,
        ...team2Data
      },
      matchPhase: 'unknown'
    };
    
    // Determine match phase
    if (team1Data.overs > 0 && team2Data.overs === 0) {
      matchState.matchPhase = 'firstInnings';
    } else if (team1Data.overs > 0 && team2Data.overs > 0) {
      matchState.matchPhase = 'secondInnings';
    }
    
    // Use ML model for prediction if available
    let team1Chance = 50;
    let team2Chance = 50;
    let factors = [];
    
    if (predictionModel) {
      try {
        // Prepare input data for the model
        const inputData = [
          team1Data.runs, 
          team1Data.wickets, 
          team1Data.overs,
          team2Data.runs,
          team2Data.wickets,
          team2Data.overs
        ];
        
        // Make prediction
        const inputTensor = TensorFlow.tensor2d([inputData]);
        const prediction = predictionModel.predict(inputTensor);
        const predictionData = await prediction.data();
        
        team1Chance = Math.round(predictionData[0] * 100);
        team2Chance = 100 - team1Chance;
        
        // Generate factors based on match state
        if (matchState.matchPhase === 'firstInnings') {
          factors = [
            `${team1Name} has scored ${team1Data.runs} runs in ${team1Data.overs} overs`,
            `Current run rate is ${(team1Data.runs / team1Data.overs).toFixed(2)}`,
            `${team1Name} has lost ${team1Data.wickets} wickets`
          ];
        } else if (matchState.matchPhase === 'secondInnings') {
          const runsNeeded = team1Data.runs - team2Data.runs;
          const ballsRemaining = Math.floor((50 - team2Data.overs) * 6);
          
          if (runsNeeded > 0) {
            factors = [
              `${team2Name} needs ${runsNeeded} runs from approximately ${ballsRemaining} balls`,
              `Required run rate is ${(runsNeeded / ((50 - team2Data.overs) / 6)).toFixed(2)}`,
              `${team2Name} has ${10 - team2Data.wickets} wickets remaining`
            ];
          } else {
            factors = [
              `${team2Name} has won the match`,
              `${team2Name} won by ${10 - team2Data.wickets} wickets`
            ];
            team1Chance = 0;
            team2Chance = 100;
          }
        }
      } catch (modelError) {
        console.error('Error using prediction model:', modelError);
        // Fallback to basic prediction if model fails
        if (matchState.matchPhase === 'secondInnings') {
          const runsNeeded = team1Data.runs - team2Data.runs;
          if (runsNeeded <= 0) {
            team1Chance = 0;
            team2Chance = 100;
          } else {
            const totalOvers = 50; // assuming ODI
            const ballsRemaining = Math.floor((totalOvers - team2Data.overs) * 6);
            const reqRunRate = runsNeeded / (ballsRemaining / 6);
            const wicketsLost = team2Data.wickets;
            
            // Simple prediction based on required run rate and wickets
            if (reqRunRate > 12) {
              team1Chance = 80;
              team2Chance = 20;
            } else if (reqRunRate > 8) {
              team1Chance = 60;
              team2Chance = 40;
            } else if (reqRunRate > 6) {
              team1Chance = 40;
              team2Chance = 60;
            } else {
              team1Chance = 20;
              team2Chance = 80;
            }
            
            // Adjust based on wickets
            if (wicketsLost >= 7) {
              team1Chance += 20;
              team2Chance -= 20;
            }
            
            // Ensure values are within range
            team1Chance = Math.max(0, Math.min(100, team1Chance));
            team2Chance = 100 - team1Chance;
          }
          
          factors = [
            `Required run rate analysis`,
            `Wickets remaining factor`,
            `Historical chase success rate`
          ];
        }
      }
    }
    
    res.json({
      team1Chance,
      team2Chance,
      factors
    });
  } catch (error) {
    console.error('Error in /api/matches/:matchId/prediction:', error);
    res.status(500).json({ error: 'Failed to generate match prediction' });
  }
});

// Get points table for a series
app.get('/api/series/:seriesId/points', async (req, res) => {
  try {
    const { seriesId } = req.params;
    const html = await fetchCricbuzzPage(`${CRICBUZZ_URL}/cricket-series/${seriesId}/points-table`);
    const $ = cheerio.load(html);
    
    const pointsTable = [];
    
    $('.cb-srs-pnts').each((i, element) => {
      const tableEl = $(element);
      const rows = tableEl.find('tr');
      
      // Skip header row
      rows.slice(1).each((rowIndex, row) => {
        const columns = $(row).find('td');
        
        if (columns.length > 0) {
          pointsTable.push({
            position: columns.eq(0).text().trim(),
            team: columns.eq(1).text().trim(),
            matches: parseInt(columns.eq(2).text().trim(), 10),
            won: parseInt(columns.eq(3).text().trim(), 10),
            lost: parseInt(columns.eq(4).text().trim(), 10),
            tied: parseInt(columns.eq(5).text().trim(), 10),
            noResult: parseInt(columns.eq(6).text().trim(), 10),
            points: parseInt(columns.eq(7).text().trim(), 10),
            netRunRate: parseFloat(columns.eq(8).text().trim())
          });
        }
      });
    });
    
    res.json(pointsTable);
  } catch (error) {
    console.error(`Error in /api/series/:seriesId/points:`, error);
    res.status(500).json({ error: 'Failed to fetch points table' });
  }
});

// Get match highlights
app.get('/api/matches/:matchId/highlights', async (req, res) => {
  try {
    const { matchId } = req.params;
    const html = await fetchCricbuzzPage(`${CRICBUZZ_URL}/cricket-match/live-scores/${matchId}`);
    const $ = cheerio.load(html);
    
    const highlights = [];
    
    // Extract key moments/highlights
    $('.cb-mat-key-evt').each((i, element) => {
      const highlightEl = $(element);
      const text = highlightEl.text().trim();
      const timestamp = highlightEl.find('.cb-mat-key-evt-time').text().trim();
      
      highlights.push({
        text: text.replace(timestamp, '').trim(),
        timestamp,
        type: text.includes('FOUR') || text.includes('SIX') ? 'boundary' : 
              text.includes('WICKET') ? 'wicket' : 'other'
      });
    });
    
    res.json(highlights);
  } catch (error) {
    console.error(`Error in /api/matches/:matchId/highlights:`, error);
    res.status(500).json({ error: 'Failed to fetch match highlights' });
  }
});

// Start the server
app.listen(PORT, () => {
  console.log(`Server is running on port ${PORT}`);
});
