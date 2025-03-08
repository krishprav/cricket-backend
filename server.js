const express = require('express');
const http = require('http');
const WebSocket = require('ws');
const { spawn } = require('child_process');
const path = require('path');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');
const cors = require('cors');
require('dotenv').config();

const app = express();
const server = http.createServer(app);
const wss = new WebSocket.Server({ server, path: '/live-scores' });

// Enhanced security middleware
app.use(helmet({
  contentSecurityPolicy: {
    directives: {
      ...helmet.contentSecurityPolicy.getDefaultDirectives(),
      'img-src': ["'self'", "data:", "*.cricbuzz.com"],
      'script-src': ["'self'", "'unsafe-inline'"],
    }
  },
  crossOriginEmbedderPolicy: false
}));

// Rate limiting
const apiLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 150,
  standardHeaders: true,
  legacyHeaders: false,
});

// CORS configuration
const allowedOrigins = [
  'http://localhost:3000',
  'https://your-production-domain.com'
];

app.use(cors({
  origin: allowedOrigins,
  methods: ['GET', 'POST', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'Authorization'],
  credentials: true
}));

app.use(express.json());
app.use(express.static(path.join(__dirname, '../frontend/out')));
app.use('/matches', apiLimiter);

// Enhanced caching with TTL
const matchCache = new Map();
const CACHE_TTL = 15000; // 15 seconds

// WebSocket heartbeat
const HEARTBEAT_INTERVAL = 30000;
const subscribers = new Map();

function getMatchData(matchId, callback) {
  const cacheKey = matchId || 'list';
  const cached = matchCache.get(cacheKey);

  if (cached && Date.now() - cached.timestamp < CACHE_TTL) {
    return callback(cached.data);
  }

  const pythonProcess = spawn('python3', ['scraper.py', matchId]);
  let dataBuffer = '';
  let errorBuffer = '';

  pythonProcess.stdout.on('data', (chunk) => {
    dataBuffer += chunk.toString();
  });

  pythonProcess.stderr.on('data', (chunk) => {
    errorBuffer += chunk.toString();
  });

  pythonProcess.on('close', (code) => {
    if (code !== 0 || errorBuffer) {
      console.error(`Scraper error: ${errorBuffer}`);
      return callback({ error: 'Data fetch failed' });
    }

    try {
      const result = JSON.parse(dataBuffer);
      matchCache.set(cacheKey, {
        data: result,
        timestamp: Date.now()
      });
      callback(result);
    } catch (e) {
      console.error('JSON parse error:', e);
      callback({ error: 'Invalid data format' });
    }
  });
}

// HTTP endpoints
app.get('/matches', (req, res) => {
  const matchId = req.query.matchId || 'list';
  
  getMatchData(matchId, (data) => {
    if (data.error) {
      return res.status(500).json(data);
    }
    res.json(data);
  });
});

app.get('/matches/:matchId', (req, res) => {
  const { matchId } = req.params;
  
  getMatchData(matchId, (data) => {
    if (!data || data.error) {
      return res.status(404).json({ error: 'Match not found' });
    }
    res.json(data);
  });
});

// WebSocket handling
wss.on('connection', (ws, req) => {
  const origin = req.headers.origin;
  if (!allowedOrigins.includes(origin)) {
    return ws.close(1008, 'Origin not allowed');
  }

  let isAlive = true;
  const heartbeat = () => isAlive = true;
  const interval = setInterval(() => {
    if (!isAlive) return ws.terminate();
    isAlive = false;
    ws.ping();
  }, HEARTBEAT_INTERVAL);

  ws.on('pong', heartbeat);
  ws.on('message', (message) => {
    try {
      const { type, matchId } = JSON.parse(message);
      if (type === 'subscribe') {
        if (!subscribers.has(matchId)) {
          subscribers.set(matchId, new Set());
        }
        subscribers.get(matchId).add(ws);
      }
    } catch (e) {
      console.error('Invalid WS message:', message);
    }
  });

  ws.on('close', () => {
    clearInterval(interval);
    subscribers.forEach((clients, matchId) => {
      clients.delete(ws);
      if (clients.size === 0) {
        subscribers.delete(matchId);
      }
    });
  });
});

// Broadcast updates
setInterval(() => {
  subscribers.forEach((clients, matchId) => {
    if (clients.size === 0) return;

    getMatchData(matchId, (data) => {
      clients.forEach(ws => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify(data));
        }
      });
    });
  });
}, 10000); // Update every 10 seconds

// Error handling
app.use((err, req, res, next) => {
  console.error(err.stack);
  res.status(500).json({ 
    error: 'Internal Server Error',
    message: process.env.NODE_ENV === 'development' ? err.message : null
  });
});

process.on('unhandledRejection', (reason, promise) => {
  console.error('Unhandled Rejection at:', promise, 'reason:', reason);
});

process.on('uncaughtException', (error) => {
  console.error('Uncaught Exception:', error);
  process.exit(1);
});

// Start server
const PORT = process.env.PORT || 8080;
server.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
  console.log(`WebSocket server available at ws://localhost:${PORT}/live-scores`);
});