#!/usr/bin/env node
// fleet-bus-server.js — Real-time session bus for claude-fleet.
//
// A tiny always-on HTTP server (zero dependencies — Node's built-in `http`
// only) that lets a Claude Code session on one machine message a session on
// another machine in real time. Complements the async git-inbox system
// (docs/05-inbox-system.md): the inbox is durable and works with nobody
// listening; the bus is ephemeral and instant when somebody is.
//
// Run it on any always-on machine (a spare box, a cloud VM, the same host
// as the Control Center):
//   node fleet-bus-server.js [--port 4100]
//
// Endpoints:
//   POST /send    {to, from, to_session?, from_session?, body}  -> queue+push
//   GET  /poll    ?machine=&session=&waitSeconds=   -> long-poll receive
//   GET  /sessions -> who is currently listening, fleet-wide
//   GET  /health
//
// Delivery model: if a listener is already long-polling for the target
// machine/session, the message resolves that poll immediately (delivered).
// Otherwise it sits in the in-memory queue until the target's next poll
// (queued). Restarting the server clears the queue — this is intentionally
// ephemeral, not a replacement for the durable git inbox.
//
// Auth (optional): set FLEET_BUS_TOKEN to require senders to pass a
// matching X-Fleet-Token header. Unset by default — same trust model as the
// rest of claude-fleet, which assumes a private Tailscale mesh. Reads (poll,
// sessions, health) are never gated, since a listener has nothing to hide by
// announcing it's listening.
//
// See docs/16-session-bus.md for the full architecture + the Claude Code
// Monitor-hook recipe that lets a live session receive these messages.

const http = require('http');
const crypto = require('crypto');

const PORT = parseInt(process.env.PORT || process.argv.find(a => a.startsWith('--port='))?.split('=')[1] || '4100', 10);
const TOKEN = process.env.FLEET_BUS_TOKEN || '';
const MAX_BODY = 4000;
const MAX_WAIT_SECONDS = 60;

// In-memory only — see header comment. { id, created, from, fromSession, to, toSession, body, delivered }
let nextId = 1;
const messages = [];
// pollers waiting on a poll: [{ machine, session, res, timer }]
let pollers = [];

function timingSafeEqual(a, b) {
  const ab = Buffer.from(String(a));
  const bb = Buffer.from(String(b));
  return ab.length === bb.length && crypto.timingSafeEqual(ab, bb);
}

function tokenOk(req) {
  if (!TOKEN) return true;
  return timingSafeEqual(req.headers['x-fleet-token'] || '', TOKEN);
}

function readJsonBody(req, cb) {
  let raw = '';
  let tooLarge = false;
  req.on('data', chunk => {
    raw += chunk;
    if (raw.length > 65536) { tooLarge = true; req.destroy(); }
  });
  req.on('end', () => {
    if (tooLarge) return cb(new Error('body too large'));
    try { cb(null, raw ? JSON.parse(raw) : {}); }
    catch (e) { cb(new Error('invalid JSON')); }
  });
}

function matches(poller, msg) {
  if (poller.machine !== msg.to) return false;
  if (msg.toSession && msg.toSession !== poller.session) return false;
  return true;
}

function resolvePoller(p, msgs) {
  clearTimeout(p.timer);
  pollers = pollers.filter(x => x !== p);
  try {
    p.res.writeHead(200, { 'Content-Type': 'application/json' });
    p.res.end(JSON.stringify(msgs));
  } catch (e) { /* client already gone */ }
}

function deliver(msg) {
  let delivered = false;
  for (const p of pollers.filter(p => matches(p, msg))) {
    resolvePoller(p, [msg]);
    delivered = true;
  }
  msg.delivered = delivered;
  return delivered;
}

function backlogFor(machine, session) {
  const undelivered = messages.filter(m => m.to === machine && !m.delivered && (!m.toSession || m.toSession === session));
  undelivered.forEach(m => { m.delivered = true; });
  return undelivered;
}

function json(res, status, obj) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(obj));
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);

  if (req.method === 'GET' && url.pathname === '/health') {
    return json(res, 200, { ok: true, messages: messages.length, listeners: pollers.length });
  }

  if (req.method === 'GET' && url.pathname === '/sessions') {
    return json(res, 200, pollers.map(p => ({ machine: p.machine, session: p.session, since: p.since })));
  }

  if (req.method === 'GET' && url.pathname === '/messages') {
    const machine = (url.searchParams.get('machine') || '').toLowerCase().trim();
    const rows = machine ? messages.filter(m => m.to === machine) : messages;
    return json(res, 200, rows.slice(-50));
  }

  if (req.method === 'GET' && url.pathname === '/poll') {
    const machine = (url.searchParams.get('machine') || '').toLowerCase().trim();
    const session = url.searchParams.get('session') || `anon-${Math.random().toString(36).slice(2, 8)}`;
    if (!machine) return json(res, 400, { error: 'machine query param required' });
    const waitSeconds = Math.min(Math.max(parseInt(url.searchParams.get('waitSeconds'), 10) || 25, 1), MAX_WAIT_SECONDS);

    const backlog = backlogFor(machine, session);
    if (backlog.length) return json(res, 200, backlog);

    const p = { machine, session, res, since: new Date().toISOString(), timer: null };
    pollers.push(p);
    p.timer = setTimeout(() => resolvePoller(p, []), waitSeconds * 1000);
    req.on('close', () => { clearTimeout(p.timer); pollers = pollers.filter(x => x !== p); });
    return;
  }

  if (req.method === 'POST' && url.pathname === '/send') {
    if (!tokenOk(req)) return json(res, 401, { error: 'missing or invalid X-Fleet-Token' });
    return readJsonBody(req, (err, body) => {
      if (err) return json(res, 400, { error: err.message });
      const to = String(body.to || '').toLowerCase().trim();
      const from = String(body.from || '').toLowerCase().trim();
      const text = String(body.body || '').trim();
      if (!to || !from || !text) return json(res, 400, { error: 'to, from, body are required' });
      if (text.length > MAX_BODY) return json(res, 413, { error: `body over ${MAX_BODY} chars — write it to the KB and send the path instead` });

      const msg = {
        id: nextId++,
        created: new Date().toISOString(),
        to, from,
        toSession: body.to_session ? String(body.to_session) : null,
        fromSession: body.from_session ? String(body.from_session) : null,
        body: text,
        delivered: false,
      };
      messages.push(msg);
      const delivered = deliver(msg);
      return json(res, 200, { id: msg.id, delivered_live: delivered, queued: !delivered });
    });
  }

  json(res, 404, { error: 'not found', endpoints: ['POST /send', 'GET /poll', 'GET /sessions', 'GET /messages', 'GET /health'] });
});

server.listen(PORT, () => {
  console.log(`[fleet-bus] listening on :${PORT}${TOKEN ? ' (token required for /send)' : ' (no auth — set FLEET_BUS_TOKEN to require one)'}`);
});
