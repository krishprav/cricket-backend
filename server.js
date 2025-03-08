const express = require('express');
const http = require('http');
const WebSocket = require('ws');
const { spawn } = require('child_process');
const path = require('path');
require('dotenv').config();

const app = express();
const server = http.createServer(app);
const wss = new WebSocket.Server({ server });

const subscribers = {};

// Serve frontend static files (for combined hosting)
app.use(express.static(path.join(__dirname, '../frontend/.next')));
app.use(express.static(path.join(__dirname, '../frontend/public')));

// Function to execute Python scraper
function getMatchData(matchId, callback) {
  const pythonProcess = spawn('python', ['scraper.py', matchId]);
  let data = '';
  let error = '';

  pythonProcess.stdout.on('data', (chunk) => {
    data += chunk.toString();
  });

  pythonProcess.stderr.on('data', (chunk) => {
    error += chunk.toString();
  });

  pythonProcess.on('close', (code) => {
    if (code !== 0) {
      console.error(`Scraper exited with code ${code}: ${error}`);
      callback(null);
      return;
    }
    try {
      const result = JSON.parse(data);
      callback(result);
    } catch (e) {
      console.error(`Error parsing scraper output for match ${matchId}: ${e.message}`);
      callback(null);
    }
  });
}

// HTTP endpoint for match list or specific match data
app.get('/matches', (req, res) => {
  const matchId = req.query.matchId || 'list';
  getMatchData(matchId, (data) => {
    if (data) {
      res.json(data);
    } else {
      res.status(500).json({ error: 'Failed to fetch match data' });
    }
  });
});

// WebSocket handling
wss.on('connection', (ws) => {
  ws.on('message', (message) => {
    try {
      const data = JSON.parse(message);
      if (data.type === 'subscribe') {
        const matchId = data.matchId;
        if (!subscribers[matchId]) subscribers[matchId] = [];
        subscribers[matchId].push(ws);
        console.log(`Client subscribed to match ${matchId}`);
      }
    } catch (e) {
      console.error('Error parsing WebSocket message:', e.message);
    }
  });

  ws.on('close', () => {
    for (const matchId in subscribers) {
      subscribers[matchId] = subscribers[matchId].filter((client) => client !== ws);
      if (subscribers[matchId].length === 0) delete subscribers[matchId];
    }
  });

  ws.on('error', (error) => {
    console.error('WebSocket error:', error.message);
  });
});

// Poll and broadcast updates every 30 seconds
setInterval(() => {
  for (const matchId in subscribers) {
    if (subscribers[matchId].length > 0) {
      getMatchData(matchId, (matchData) => {
        if (matchData) {
          subscribers[matchId].forEach((ws) => {
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify(matchData));
            }
          });
        } else {
          console.log(`No data available for match ${matchId}`);
        }
      });
    }
  }
}, 30000);

server.listen(process.env.PORT || 8080, () => {
  console.log(`Backend server running on port ${process.env.PORT || 8080}`);
});