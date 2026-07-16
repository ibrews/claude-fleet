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
//   POST /role/claim  {role, machine, session}                  -> register holder
//   GET  /role/whois  ?role=                                    -> holder + liveness + history
//   POST /role/retire {role, to_machine?, to_session, reason, window_hours?} -> handoff + redirect
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
// Roles — durable ownership for a recurring job (e.g. "build-orchestrator"),
// so a free-text session slug can't silently collide the way two sessions
// registering the same string did in the field (see docs/16-session-bus.md
// § Roles for the incident this fixes):
//   POST /role/claim   {role, machine, session}            -> register holder
//   GET  /role/whois   ?role=                              -> holder + liveness + history
//   POST /role/retire  {role, to_machine, to_session, reason, window_hours?}
// The current holder of a role is simply the most recent 'claim' event for
// it — an append-only in-memory log, same last-write-wins shape as the rest
// of this file (no separate "current state" table to keep in sync). Liveness
// is driven by `lastSeen`, a plain Map updated on every /poll hit — traffic
// the bus already receives from `listen`'s long-poll loop — so it works
// without any new client-side heartbeat.
//
// See docs/16-session-bus.md for the full architecture + the Claude Code
// Monitor-hook recipe that lets a live session receive these messages.

const http = require('http');
const https = require('https');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const os = require('os');

const PORT = parseInt(process.env.PORT || process.argv.find(a => a.startsWith('--port='))?.split('=')[1] || '4100', 10);
const TOKEN = process.env.FLEET_BUS_TOKEN || '';
const MAX_BODY = 4000;
const MAX_WAIT_SECONDS = 60;

// ── Optional: relay `--to human` to Telegram via fleet-bot's own bot ──────
// Nobody will ever poll as machine "human", so instead of queuing forever,
// treat it as a reserved target: if fleet-bot's credentials file exists
// (~/claude-fleet/fleet.env — see telegram/fleet-bot/README.md), relay the
// message there. Entirely optional — with no fleet.env, `--to human` just
// queues like any other machine (nobody will ever come collect it; that's a
// signal you haven't set up fleet-bot, not a crash).
function loadTelegramCreds() {
  const envPath = path.join(os.homedir(), 'claude-fleet', 'fleet.env');
  const creds = {};
  try {
    for (const line of fs.readFileSync(envPath, 'utf8').split('\n')) {
      const m = line.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$/);
      if (m) creds[m[1]] = m[2].replace(/^["']|["']$/g, '');
    }
  } catch (e) { /* no fleet-bot set up — human relay just queues, see above */ }
  return creds;
}
const TELEGRAM = loadTelegramCreds();

function sendTelegram(text) {
  return new Promise((resolve, reject) => {
    if (!TELEGRAM.TELEGRAM_BOT_TOKEN || !TELEGRAM.TELEGRAM_CHAT_ID) {
      return reject(new Error('~/claude-fleet/fleet.env missing or incomplete — see telegram/fleet-bot/README.md'));
    }
    const payload = JSON.stringify({ chat_id: TELEGRAM.TELEGRAM_CHAT_ID, text, parse_mode: 'HTML' });
    const req = https.request({
      hostname: 'api.telegram.org',
      path: `/bot${TELEGRAM.TELEGRAM_BOT_TOKEN}/sendMessage`,
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(payload) },
      timeout: 10000,
    }, (res) => {
      let raw = '';
      res.on('data', c => raw += c);
      res.on('end', () => {
        let parsed;
        try { parsed = JSON.parse(raw); } catch (e) { return reject(new Error(`bad Telegram response: ${raw.slice(0, 200)}`)); }
        if (!parsed.ok) return reject(new Error(parsed.description || 'Telegram sendMessage failed'));
        resolve(parsed.result);
      });
    });
    req.on('timeout', () => req.destroy(new Error('Telegram request timed out')));
    req.on('error', reject);
    req.write(payload);
    req.end();
  });
}

function escHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// In-memory only — see header comment. { id, created, from, fromSession, to, toSession, body, delivered }
let nextId = 1;
const messages = [];
// pollers waiting on a poll: [{ machine, session, res, timer }]
let pollers = [];

// ── Roles: durable ownership on top of the raw machine/session routing ────
// Append-only log, one entry per claim/retire. In-memory only, like
// everything else in this file — a restart clears roles the same way it
// clears the message queue (there's no durable-store expectation here; see
// docs/16-session-bus.md § Roles for why the internal/SQLite-backed version
// this was ported from doesn't apply to the public in-memory server).
const roleEvents = []; // { role, event: 'claim'|'retire', machine, session, at, reason? }
// `${machine}/${session}` -> last-seen epoch ms. Updated on every /poll hit
// (both an immediate backlog return and a fresh long-poll registration), so
// liveness is derived from traffic the bus already receives — no separate
// client heartbeat needed, and it's OS-agnostic.
const lastSeen = new Map();
const STALE_MS = 15 * 60 * 1000; // 15 minutes — see design doc for why

function touchLastSeen(machine, session) {
  if (!machine || !session) return;
  lastSeen.set(`${machine}/${session}`, Date.now());
}

function currentHolder(role) {
  for (let i = roleEvents.length - 1; i >= 0; i--) {
    const e = roleEvents[i];
    if (e.role === role && e.event === 'claim') return e;
  }
  return null;
}

function roleHistory(role, limit = 6) {
  return roleEvents.filter(e => e.role === role).slice(-limit);
}

function liveness(machine, session) {
  const seenAt = lastSeen.get(`${machine}/${session}`);
  if (!seenAt) return { status: 'stale', last_seen_at: null, seconds_since: null };
  const secondsSince = Math.round((Date.now() - seenAt) / 1000);
  return {
    status: secondsSince * 1000 <= STALE_MS ? 'live' : 'stale',
    last_seen_at: new Date(seenAt).toISOString(),
    seconds_since: secondsSince,
  };
}

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

    // Every poll — whether it resolves immediately or parks — is proof this
    // machine/session pair is alive. This is the only liveness signal roles
    // use (see touchLastSeen definition above); no separate heartbeat call.
    touchLastSeen(machine, session);

    const backlog = backlogFor(machine, session);
    if (backlog.length) return json(res, 200, backlog);

    const p = { machine, session, res, since: new Date().toISOString(), timer: null };
    pollers.push(p);
    p.timer = setTimeout(() => resolvePoller(p, []), waitSeconds * 1000);
    req.on('close', () => { clearTimeout(p.timer); pollers = pollers.filter(x => x !== p); });
    return;
  }

  if (req.method === 'POST' && url.pathname === '/role/claim') {
    if (!tokenOk(req)) return json(res, 401, { error: 'missing or invalid X-Fleet-Token' });
    return readJsonBody(req, (err, body) => {
      if (err) return json(res, 400, { error: err.message });
      const role = String(body.role || '').trim();
      const machine = String(body.machine || '').toLowerCase().trim();
      const session = String(body.session || '').trim();
      if (!role || !machine || !session) return json(res, 400, { error: 'role, machine, session are required' });
      const entry = { role, event: 'claim', machine, session, at: new Date().toISOString() };
      roleEvents.push(entry);
      touchLastSeen(machine, session); // claiming counts as a check-in
      return json(res, 200, { role, holder: entry });
    });
  }

  if (req.method === 'GET' && url.pathname === '/role/whois') {
    const role = (url.searchParams.get('role') || '').trim();
    if (!role) return json(res, 400, { error: 'role query param required' });
    const holder = currentHolder(role);
    if (!holder) return json(res, 200, { role, holder: null, liveness: null, history: [] });
    return json(res, 200, {
      role,
      holder,
      liveness: liveness(holder.machine, holder.session),
      history: roleHistory(role),
    });
  }

  if (req.method === 'POST' && url.pathname === '/role/retire') {
    if (!tokenOk(req)) return json(res, 401, { error: 'missing or invalid X-Fleet-Token' });
    return readJsonBody(req, (err, body) => {
      if (err) return json(res, 400, { error: err.message });
      const role = String(body.role || '').trim();
      const toMachine = String(body.to_machine || '').toLowerCase().trim();
      const toSession = String(body.to_session || '').trim();
      const reason = String(body.reason || '').trim();
      if (!role || !toSession || !reason) return json(res, 400, { error: 'role, to_session, reason are required (to_machine optional)' });
      const windowHours = Math.max(parseFloat(body.window_hours) || 6, 0.1);

      // Atomic: log the retire (if there was a previous holder) then the new
      // claim in the same tick, so a concurrent whois can never observe the
      // role with no current holder mid-handoff.
      const prev = currentHolder(role);
      if (prev) roleEvents.push({ role, event: 'retire', machine: prev.machine, session: prev.session, at: new Date().toISOString(), reason });
      const newHolder = { role, event: 'claim', machine: toMachine || null, session: toSession, at: new Date().toISOString() };
      roleEvents.push(newHolder);
      if (toMachine) touchLastSeen(toMachine, toSession);

      // Redirect notice: anyone who messaged the OLD holder recently was
      // presumably trying to reach this role, not that specific session id.
      // Scan the in-memory message log directly — no separate filtered
      // endpoint is needed here (unlike the internal SQLite-backed version
      // this was ported from) because the retire handler runs in the same
      // process that already holds `messages`.
      const redirected = [];
      if (prev) {
        const cutoff = Date.now() - windowHours * 3600 * 1000;
        const seen = new Set();
        for (const m of messages) {
          if (m.to !== prev.machine) continue;
          if (m.toSession && m.toSession !== prev.session) continue;
          if (new Date(m.created).getTime() < cutoff) continue;
          if (!m.from || !m.fromSession) continue;
          const key = `${m.from}/${m.fromSession}`;
          if (seen.has(key)) continue;
          seen.add(key);
          const redirectMsg = {
            id: nextId++,
            created: new Date().toISOString(),
            to: m.from,
            from: toMachine || (prev.machine || 'fleet-bus'),
            toSession: m.fromSession,
            fromSession: toSession,
            body: `orchestration handoff: role '${role}' handed off from ${(prev.machine || '?')}/${prev.session} `
                + `to ${(toMachine || '?')}/${toSession} — reason: ${reason}. Address future messages there `
                + `(--to-role ${role} or --to-session ${toSession}).`,
            delivered: false,
          };
          messages.push(redirectMsg);
          deliver(redirectMsg);
          redirected.push(key);
        }
      }

      return json(res, 200, { role, previous_holder: prev, new_holder: newHolder, redirected, reason });
    });
  }

  if (req.method === 'POST' && url.pathname === '/send') {
    if (!tokenOk(req)) return json(res, 401, { error: 'missing or invalid X-Fleet-Token' });
    return readJsonBody(req, async (err, body) => {
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

      // `--to human` never has a poller — relay to Telegram instead (see
      // loadTelegramCreds above). Tagged #sid=/#machine= so a reply in
      // Telegram can route back via fleet-bot's existing reply-router
      // (telegram/fleet-bot/bot.mjs already understands this tag format).
      if (to === 'human') {
        const tag = msg.fromSession ? `\n\n#sid=${escHtml(msg.fromSession)} #machine=${escHtml(msg.from)}` : '';
        try {
          await sendTelegram(`🔔 <b>${escHtml(msg.from)}</b>: ${escHtml(msg.body)}${tag}`);
          msg.delivered = true;
          return json(res, 200, { id: msg.id, delivered_live: true, queued: false, via: 'telegram' });
        } catch (e) {
          return json(res, 502, { id: msg.id, delivered_live: false, queued: true, error: `telegram relay failed: ${e.message}` });
        }
      }

      const delivered = deliver(msg);
      return json(res, 200, { id: msg.id, delivered_live: delivered, queued: !delivered });
    });
  }

  json(res, 404, {
    error: 'not found',
    endpoints: ['POST /send', 'GET /poll', 'GET /sessions', 'GET /messages', 'GET /health',
                'POST /role/claim', 'GET /role/whois', 'POST /role/retire'],
  });
});

server.listen(PORT, () => {
  console.log(`[fleet-bus] listening on :${PORT}${TOKEN ? ' (token required for /send)' : ' (no auth — set FLEET_BUS_TOKEN to require one)'}`);
});
