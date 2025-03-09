const express = require('express');
const http = require('http');
const WebSocket = require('ws');
const { spawn } = require('child_process');
const path = require('path');
const cors = require('cors');
const fs = require('fs');
require('dotenv').config();

const app = express();
const server = http.createServer(app);
const wss = new WebSocket.Server({ server });

// Data caching system (in-memory)
const cache = {
  matches: {},
  matchList: { data: null, timestamp: 0 },
  pointsTables: {},
  players: {}
};

// Cache expiry times (in milliseconds)
const CACHE_EXPIRY = {
  matchList: 5 * 60 * 1000, // 5 minutes
  matchData: 30 * 1000,     // 30 seconds
  commentary: 10 * 1000,    // 10 seconds
  pointsTable: 60 * 60 * 1000, // 1 hour
  playerStats: 24 * 60 * 60 * 1000 // 24 hours
};

// Track subscribers for different data types
const subscribers = {
  matches: {},
  commentary: {},
  pointsTables: {}
};

// Configure CORS with specific origins or use environment variables
const allowedOrigins = process.env.ALLOWED_ORIGINS
  ? process.env.ALLOWED_ORIGINS.split(',')
  : ['https://cricket-gray.vercel.app', 'http://localhost:3000', '*'];

app.use(cors({
  origin: (origin, callback) => {
    // Allow requests with no origin (like mobile apps)
    if (!origin || allowedOrigins.includes('*') || allowedOrigins.includes(origin)) {
      callback(null, true);
    } else {
      callback(new Error('Not allowed by CORS'));
    }
  },
  methods: ['GET', 'POST'],
  credentials: true
}));

// Add JSON parsing middleware
app.use(express.json());

// Check if frontend paths exist before serving static files
const nextBuildPath = path.join(__dirname, '../frontend/.next');
const publicPath = path.join(__dirname, '../frontend/public');

// Serve frontend static files only if directories exist
if (fs.existsSync(nextBuildPath)) {
  console.log('Serving Next.js build files from:', nextBuildPath);
  app.use(express.static(nextBuildPath));
} else {
  console.log('Next.js build directory not found:', nextBuildPath);
}

if (fs.existsSync(publicPath)) {
  console.log('Serving public files from:', publicPath);
  app.use(express.static(publicPath));
} else {
  console.log('Public directory not found:', publicPath);
}

// Function to execute Python scraper with caching
function getMatchData(matchId, command = null, forceFresh = false, callback) {
  // Determine cache key and expiry based on command
  let cacheKey = matchId;
  let cacheExpiry = CACHE_EXPIRY.matchData;
  
  if (command === 'list') {
    cacheKey = 'matchList';
    cacheExpiry = CACHE_EXPIRY.matchList;
  } else if (command === 'commentary') {
    cacheKey = `commentary_${matchId}`;
    cacheExpiry = CACHE_EXPIRY.commentary;
  } else if (command === 'points') {
    cacheKey = `points_${matchId}`;
    cacheExpiry = CACHE_EXPIRY.pointsTable;
  } else if (command === 'player') {
    cacheKey = `player_${matchId}`;
    cacheExpiry = CACHE_EXPIRY.playerStats;
  }
  
  // Check cache if not forcing fresh data
  if (!forceFresh) {
    if (command === 'list' && cache.matchList.data && 
        (Date.now() - cache.matchList.timestamp) < cacheExpiry) {
      console.log('Serving match list from cache');
      return callback(cache.matchList.data);
    }
    
    if (command === 'points' && cache.pointsTables[matchId] && 
        (Date.now() - cache.pointsTables[matchId].timestamp) < cacheExpiry) {
      console.log(`Serving points table ${matchId} from cache`);
      return callback(cache.pointsTables[matchId].data);
    }
    
    if (command === 'player' && cache.players[matchId] && 
        (Date.now() - cache.players[matchId].timestamp) < cacheExpiry) {
      console.log(`Serving player ${matchId} from cache`);
      return callback(cache.players[matchId].data);
    }
    
    if (!command && cache.matches[matchId] && 
        (Date.now() - cache.matches[matchId].timestamp) < cacheExpiry) {
      console.log(`Serving match ${matchId} from cache`);
      return callback(cache.matches[matchId].data);
    }
    
    if (command === 'commentary' && cache.matches[cacheKey] && 
        (Date.now() - cache.matches[cacheKey].timestamp) < cacheExpiry) {
      console.log(`Serving commentary for match ${matchId} from cache`);
      return callback(cache.matches[cacheKey].data);
    }
  }
  
  // Prepare Python command arguments
  const args = ['scraper.py'];
  if (command === 'list') {
    args.push('list');
  } else if (command) {
    args.push(command, matchId);
  } else {
    args.push(matchId);
  }
  
  console.log(`Executing Python scraper with args: ${args.join(' ')}`);
  
  const pythonProcess = spawn('python', args);
  let data = '';
  let error = '';

  pythonProcess.stdout.on('data', (chunk) => {
    data += chunk.toString();
  });

  pythonProcess.stderr.on('data', (chunk) => {
    error += chunk.toString();
    console.error(`Scraper stderr: ${chunk.toString()}`);
  });

  pythonProcess.on('close', (code) => {
    if (code !== 0) {
      console.error(`Scraper exited with code ${code}: ${error}`);
      callback(null);
      return;
    }
    
    try {
      const result = JSON.parse(data);
      
      // Update cache based on command
      if (command === 'list') {
        cache.matchList = { data: result, timestamp: Date.now() };
      } else if (command === 'points') {
        cache.pointsTables[matchId] = { data: result, timestamp: Date.now() };
      } else if (command === 'player') {
        cache.players[matchId] = { data: result, timestamp: Date.now() };
      } else if (command === 'commentary') {
        cache.matches[cacheKey] = { data: result, timestamp: Date.now() };
      } else {
        cache.matches[matchId] = { data: result, timestamp: Date.now() };
      }
      
      callback(result);
    } catch (e) {
      console.error(`Error parsing scraper output for ${command || 'match'} ${matchId}: ${e.message}`);
      console.error(`Raw output: ${data.substring(0, 200)}...`);
      callback(null);
    }
  });
}

// Load cache from disk (if available)
function loadCache() {
  const cachePath = path.join(__dirname, 'cache.json');
  
  if (fs.existsSync(cachePath)) {
    try {
      const cacheData = JSON.parse(fs.readFileSync(cachePath, 'utf8'));
      
      if (cacheData.matchList) cache.matchList = cacheData.matchList;
      if (cacheData.pointsTables) cache.pointsTables = cacheData.pointsTables;
      if (cacheData.players) cache.players = cacheData.players;
      
      console.log('Cache loaded from disk');
    } catch (err) {
      console.error('Error loading cache from disk:', err);
    }
  }
}

// Save cache to disk periodically
function saveCache() {
  const cachePath = path.join(__dirname, 'cache.json');
  const cacheData = {
    matchList: cache.matchList,
    pointsTables: cache.pointsTables,
    players: cache.players
    // Don't save match data as it's too volatile
  };
  
  fs.writeFile(cachePath, JSON.stringify(cacheData), (err) => {
    if (err) console.error('Error saving cache:', err);
    else console.log('Cache saved to disk');
  });
}

// Initialize cache & set up periodic save
loadCache();
setInterval(saveCache, 15 * 60 * 1000); // Save every 15 minutes

// WebSocket connection handling
wss.on('connection', (ws) => {
  console.log('Client connected');
  
  ws.on('message', (message) => {
    try {
      const { action, matchId, tournamentId, playerId } = JSON.parse(message);
      
      // Handle different subscription types
      if (action === 'subscribe') {
        if (matchId) {
          // Subscribe to match updates
          if (!subscribers.matches[matchId]) {
            subscribers.matches[matchId] = new Set();
          }
          subscribers.matches[matchId].add(ws);
          console.log(`Client subscribed to match ${matchId}`);
          
          // Send initial data
          getMatchData(matchId, null, false, (data) => {
            if (data) {
              ws.send(JSON.stringify({
                type: 'match_update',
                data: data
              }));
            }
          });
        } else if (action === 'subscribe_commentary' && matchId) {
          // Subscribe to commentary updates
          if (!subscribers.commentary[matchId]) {
            subscribers.commentary[matchId] = new Set();
          }
          subscribers.commentary[matchId].add(ws);
          console.log(`Client subscribed to commentary for match ${matchId}`);
          
          // Send initial commentary data
          getMatchData(matchId, 'commentary', false, (data) => {
            if (data) {
              ws.send(JSON.stringify({
                type: 'commentary_update',
                data: data
              }));
            }
          });
        } else if (action === 'subscribe_points' && tournamentId) {
          // Subscribe to points table updates
          if (!subscribers.pointsTables[tournamentId]) {
            subscribers.pointsTables[tournamentId] = new Set();
          }
          subscribers.pointsTables[tournamentId].add(ws);
          console.log(`Client subscribed to points table for tournament ${tournamentId}`);
          
          // Send initial points table data
          getMatchData(tournamentId, 'points', false, (data) => {
            if (data) {
              ws.send(JSON.stringify({
                type: 'points_update',
                data: data
              }));
            }
          });
        }
      } else if (action === 'unsubscribe') {
        // Handle unsubscribe actions
        if (matchId && subscribers.matches[matchId]) {
          subscribers.matches[matchId].delete(ws);
          console.log(`Client unsubscribed from match ${matchId}`);
        }
        
        if (matchId && subscribers.commentary[matchId]) {
          subscribers.commentary[matchId].delete(ws);
          console.log(`Client unsubscribed from commentary for match ${matchId}`);
        }
        
        if (tournamentId && subscribers.pointsTables[tournamentId]) {
          subscribers.pointsTables[tournamentId].delete(ws);
          console.log(`Client unsubscribed from points table for tournament ${tournamentId}`);
        }
      }
    } catch (e) {
      console.error('Error handling WebSocket message:', e);
    }
  });
  
  ws.on('close', () => {
    console.log('Client disconnected');
    
    // Remove from all subscriptions
    for (const matchId in subscribers.matches) {
      subscribers.matches[matchId].delete(ws);
    }
    
    for (const matchId in subscribers.commentary) {
      subscribers.commentary[matchId].delete(ws);
    }
    
    for (const tournamentId in subscribers.pointsTables) {
      subscribers.pointsTables[tournamentId].delete(ws);
    }
  });
  
  // Send initial match list
  getMatchData(null, 'list', false, (data) => {
    if (data) {
      ws.send(JSON.stringify({
        type: 'match_list',
        data: data
      }));
    }
  });
});

// Set up periodic updates for subscribers
function updateSubscribers() {
  // Update match data for all subscribed clients
  for (const matchId in subscribers.matches) {
    if (subscribers.matches[matchId].size > 0) {
      getMatchData(matchId, null, true, (data) => {
        if (data) {
          const updateMessage = JSON.stringify({
            type: 'match_update',
            data: data
          });
          
          subscribers.matches[matchId].forEach(client => {
            if (client.readyState === WebSocket.OPEN) {
              client.send(updateMessage);
            }
          });
        }
      });
    }
  }
  
  // Update commentary for all subscribed clients
  for (const matchId in subscribers.commentary) {
    if (subscribers.commentary[matchId].size > 0) {
      getMatchData(matchId, 'commentary', true, (data) => {
        if (data) {
          const updateMessage = JSON.stringify({
            type: 'commentary_update',
            data: data
          });
          
          subscribers.commentary[matchId].forEach(client => {
            if (client.readyState === WebSocket.OPEN) {
              client.send(updateMessage);
            }
          });
        }
      });
    }
  }
  
  // Update points tables (less frequently)
  for (const tournamentId in subscribers.pointsTables) {
    if (subscribers.pointsTables[tournamentId].size > 0) {
      getMatchData(tournamentId, 'points', true, (data) => {
        if (data) {
          const updateMessage = JSON.stringify({
            type: 'points_update',
            data: data
          });
          
          subscribers.pointsTables[tournamentId].forEach(client => {
            if (client.readyState === WebSocket.OPEN) {
              client.send(updateMessage);
            }
          });
        }
      });
    }
  }
}

// Set different update intervals based on data type
setInterval(() => {
  // Update match list for all connected clients
  if (wss.clients.size > 0) {
    getMatchData(null, 'list', true, (data) => {
      if (data) {
        const updateMessage = JSON.stringify({
          type: 'match_list',
          data: data
        });
        
        wss.clients.forEach(client => {
          if (client.readyState === WebSocket.OPEN) {
            client.send(updateMessage);
          }
        });
      }
    });
  }
}, 60 * 1000); // Update match list every minute

// Update match data and commentary more frequently
setInterval(() => {
  updateSubscribers();
}, 15 * 1000); // Update match data and commentary every 15 seconds

// API Routes
// Get match list
app.get('/api/matches', (req, res) => {
  getMatchData(null, 'list', false, (data) => {
    if (data) {
      res.json(data);
    } else {
      res.status(500).json({ error: 'Failed to fetch match list' });
    }
  });
});

// Get specific match data
app.get('/api/matches/:matchId', (req, res) => {
  const { matchId } = req.params;
  getMatchData(matchId, null, false, (data) => {
    if (data) {
      res.json(data);
    } else {
      res.status(500).json({ error: 'Failed to fetch match data' });
    }
  });
});

// Get match commentary
app.get('/api/matches/:matchId/commentary', (req, res) => {
  const { matchId } = req.params;
  getMatchData(matchId, 'commentary', false, (data) => {
    if (data) {
      res.json(data);
    } else {
      res.status(500).json({ error: 'Failed to fetch commentary' });
    }
  });
});

// Get points table
app.get('/api/tournament/:tournamentId/points', (req, res) => {
  const { tournamentId } = req.params;
  getMatchData(tournamentId, 'points', false, (data) => {
    if (data) {
      res.json(data);
    } else {
      res.status(500).json({ error: 'Failed to fetch points table' });
    }
  });
});

// Get player stats
app.get('/api/player/:playerId', (req, res) => {
  const { playerId } = req.params;
  getMatchData(playerId, 'player', false, (data) => {
    if (data) {
      res.json(data);
    } else {
      res.status(500).json({ error: 'Failed to fetch player stats' });
    }
  });
});

// Force refresh data
app.post('/api/refresh/:type/:id', (req, res) => {
  const { type, id } = req.params;
  
  let command = null;
  if (type === 'match') {
    command = null;
  } else if (type === 'commentary') {
    command = 'commentary';
  } else if (type === 'points') {
    command = 'points';
  } else if (type === 'player') {
    command = 'player';
  } else if (type === 'list') {
    command = 'list';
  } else {
    return res.status(400).json({ error: 'Invalid refresh type' });
  }
  
  getMatchData(id, command, true, (data) => {
    if (data) {
      res.json({ success: true, data });
    } else {
      res.status(500).json({ error: 'Failed to refresh data' });
    }
  });
});

// API status route
app.get('/api/status', (req, res) => {
  res.json({
    status: 'online',
    time: new Date().toISOString(),
    version: '1.0.0'
  });
});

// Modified catch-all route for SPA frontend with error handling
app.get('*', (req, res) => {
  const indexPath = path.join(__dirname, '../frontend/.next/server/pages/index.html');
  
  // Check if the file exists before sending it
  if (fs.existsSync(indexPath)) {
    res.sendFile(indexPath);
  } else {
    // If the frontend file doesn't exist, return a simple API status page
    res.send(`
      <html>
        <head>
          <title>Cricket API Server</title>
          <style>
            body { font-family: Arial, sans-serif; line-height: 1.6; padding: 20px; max-width: 800px; margin: 0 auto; }
            h1 { color: #333; }
            .api { background: #f4f4f4; padding: 10px; border-radius: 5px; margin-bottom: 10px; }
            pre { background: #eee; padding: 10px; border-radius: 5px; overflow-x: auto; }
          </style>
        </head>
        <body>
          <h1>Cricket API Server</h1>
          <p>The API server is running successfully. The frontend is not currently available at this location.</p>
          <h2>Available API Endpoints:</h2>
          <div class="api">GET /api/status - Check API status</div>
          <div class="api">GET /api/matches - Get all matches</div>
          <div class="api">GET /api/matches/:matchId - Get specific match data</div>
          <div class="api">GET /api/matches/:matchId/commentary - Get match commentary</div>
          <div class="api">GET /api/tournament/:tournamentId/points - Get tournament points table</div>
          <div class="api">GET /api/player/:playerId - Get player statistics</div>
          <div class="api">POST /api/refresh/:type/:id - Force refresh data (types: match, commentary, points, player, list)</div>
          <h2>WebSocket API:</h2>
          <p>Available at <code>ws://${req.headers.host}</code></p>
          <pre>
// Example WebSocket usage:
const ws = new WebSocket('ws://${req.headers.host}');

// Subscribe to match updates
ws.send(JSON.stringify({
  action: 'subscribe',
  matchId: '12345'
}));

// Subscribe to commentary
ws.send(JSON.stringify({
  action: 'subscribe_commentary',
  matchId: '12345'
}));

// Subscribe to points table
ws.send(JSON.stringify({
  action: 'subscribe_points',
  tournamentId: '67890'
}));

// Listen for updates
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data.type, data.data);
};
          </pre>
        </body>
      </html>
    `);
  }
});

// Start the server
const PORT = process.env.PORT || 3001;
server.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
  console.log(`WebSocket server available at ws://localhost:${PORT}`);
});

// Handle graceful shutdown
process.on('SIGINT', () => {
  console.log('Shutting down server...');
  
  // Save cache before exiting
  saveCache();
  
  // Close server
  server.close(() => {
    console.log('Server closed');
    process.exit(0);
  });
});
