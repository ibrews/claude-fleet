#!/usr/bin/env node
// fleet-bus-client.js — talk to fleet-bus-server.js from any machine.
//
// Usage:
//   node fleet-bus-client.js send --to beta --body "your build is stale" --session my-id
//   node fleet-bus-client.js send --to beta --to-session abc123 --body "..." --session my-id
//   node fleet-bus-client.js listen --session my-id [--title "what I'm doing"]
//   node fleet-bus-client.js sessions
//   node fleet-bus-client.js history [--machine beta]   (last 50 messages, for debugging)
//
// Roles — durable ownership for a recurring job (e.g. "build-orchestrator"),
// so a free-text session slug can't silently collide the way two unrelated
// sessions registering the same string did in the field (see
// docs/16-session-bus.md § Roles for the incident this fixes):
//   node fleet-bus-client.js claim-role build-orchestrator --session my-id
//   node fleet-bus-client.js send --to-role build-orchestrator --body "..." --session my-id
//   node fleet-bus-client.js retire-role build-orchestrator --to new-session-id --reason "..."
//   node fleet-bus-client.js whois build-orchestrator
//
// Config (env vars, same names used across claude-fleet):
//   FLEET_BUS_URL      Base URL of fleet-bus-server.js (default http://localhost:4100)
//   FLEET_BUS_TOKEN     Only needed if the server was started with one set
//   FLEET_MACHINE_NAME  Your machine's name (default: hostname, lowercased) — same var
//                        used by the inbox scripts, see docs/07-hooks.md
//
// `listen` is the receive side and is meant to run under Claude Code's
// Monitor tool in COMMAND mode (not ws mode — see docs/16-session-bus.md for
// why). It blocks, long-polling the server, and prints one line per message
// so each becomes a Monitor notification. Idle listening costs zero tokens.

const http = require('http');
const os = require('os');
const { URL } = require('url');

const BASE = process.env.FLEET_BUS_URL || 'http://localhost:4100';
const TOKEN = process.env.FLEET_BUS_TOKEN || '';

function myMachine() {
  return (process.env.FLEET_MACHINE_NAME || os.hostname().split('.')[0]).toLowerCase();
}

function request(method, path, { body, token } = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(path, BASE);
    const data = body ? JSON.stringify(body) : null;
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['X-Fleet-Token'] = TOKEN;
    const req = http.request(url, { method, headers, timeout: 40000 }, res => {
      let raw = '';
      res.on('data', c => raw += c);
      res.on('end', () => {
        let parsed;
        try { parsed = JSON.parse(raw); } catch (e) { return reject(new Error(`bad response from ${BASE}: ${raw.slice(0, 200)}`)); }
        if (res.statusCode >= 400) return reject(new Error(parsed.error || `HTTP ${res.statusCode}`));
        resolve(parsed);
      });
    });
    req.on('timeout', () => req.destroy(new Error('request timed out')));
    req.on('error', reject);
    if (data) req.write(data);
    req.end();
  });
}

function parseFlags(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith('--')) { out[argv[i].slice(2)] = argv[i + 1]; i++; }
  }
  return out;
}

function frame(m) {
  const from = m.fromSession ? `${m.from}/${m.fromSession}` : m.from;
  return `[fleet-bus #${m.id} ${m.created}] from ${from}: ${m.body}`;
}

async function cmdSend(flags) {
  if (!flags.body || (!flags.to && !flags['to-role'])) {
    console.error('Usage: fleet-bus-client.js send --to <machine> --body "<text>" [--to-session <id>] [--session <my-id>]');
    console.error('   or: fleet-bus-client.js send --to-role <role> --body "<text>" [--session <my-id>]');
    process.exit(1);
  }

  let to = flags.to;
  let toSession = flags['to-session'];

  if (flags['to-role']) {
    const who = await request('GET', `/role/whois?role=${encodeURIComponent(flags['to-role'])}`);
    if (!who.holder) {
      console.error(`[fleet-bus] role '${flags['to-role']}' has never been claimed — no holder to send to. `
        + `Claim it first (claim-role) or use --to/--to-session directly.`);
      process.exit(1);
    }
    // Defensive: `machine` can be missing if the holder was claimed/retired
    // without --to-machine — guard with `|| '?'` everywhere it's displayed
    // rather than letting a template literal silently print "undefined" or,
    // worse, a caller later calling a method on it throw. Mirrors the fix
    // for the internal Python client's `TypeError` on a None `machine` field
    // (found verifying role handoff from Fort, 2026-07-16).
    to = who.holder.machine;
    toSession = who.holder.session;
    if (who.liveness && who.liveness.status !== 'live') {
      const seen = who.liveness.last_seen_at || 'never';
      console.error(`[fleet-bus] UNCERTAIN DELIVERY: role '${flags['to-role']}' has no confirmed-live holder `
        + `(last claimed by ${to || '?'}/${toSession} at ${who.holder.at}, last seen ${who.liveness.status} @ ${seen}) `
        + `— sending anyway to last-known holder.`);
    }
    if (!to) {
      console.error(`[fleet-bus] role '${flags['to-role']}' holder ${toSession} has no recorded machine — `
        + `pass --to-machine at claim time, or use --to/--to-session directly this once.`);
      process.exit(1);
    }
  }

  const out = await request('POST', '/send', {
    token: true,
    body: {
      to, from: myMachine(),
      to_session: toSession, from_session: flags.session,
      body: flags.body,
    },
  });
  console.log(`#${out.id} ${out.delivered_live ? 'delivered live' : 'queued (no live listener — delivers on next listen)'}`);
}

async function cmdClaimRole(role, flags) {
  if (!role || !flags.session) {
    console.error('Usage: fleet-bus-client.js claim-role <role> --session <my-id>');
    process.exit(1);
  }
  const machine = myMachine();
  const out = await request('POST', '/role/claim', { token: true, body: { role, machine, session: flags.session } });
  console.log(`claimed '${role}' for ${machine}/${flags.session} at ${out.holder.at}`);
}

async function cmdWhois(role) {
  if (!role) {
    console.error('Usage: fleet-bus-client.js whois <role>');
    process.exit(1);
  }
  const out = await request('GET', `/role/whois?role=${encodeURIComponent(role)}`);
  if (!out.holder) return console.log(`'${role}': never claimed`);
  const live = out.liveness || {};
  const seen = live.last_seen_at || 'never';
  console.log(`'${role}' held by ${out.holder.machine || '?'}/${out.holder.session} (claimed ${out.holder.at})`);
  console.log(`  liveness: ${(live.status || 'unknown').toUpperCase()}  (last seen ${seen}`
    + (live.seconds_since != null ? `, ${live.seconds_since}s ago` : '') + ')');
  if (out.history && out.history.length) {
    console.log('  history:');
    for (const h of out.history) {
      const tag = h.event === 'retire' ? `RETIRED (${h.reason})` : 'claimed';
      console.log(`    ${h.at}  ${tag}  ${h.machine || '?'}/${h.session}`);
    }
  }
}

async function cmdRetireRole(role, flags) {
  if (!role || !flags.to || !flags.reason) {
    console.error('Usage: fleet-bus-client.js retire-role <role> --to <new-session-id> --reason "<why>" [--to-machine <machine>] [--window-hours <n>]');
    process.exit(1);
  }
  const out = await request('POST', '/role/retire', {
    token: true,
    body: {
      role, to_session: flags.to, to_machine: flags['to-machine'],
      reason: flags.reason, window_hours: flags['window-hours'] ? parseFloat(flags['window-hours']) : undefined,
    },
  });
  const prev = out.previous_holder;
  const newHolder = out.new_holder || {};
  // Same defensive `|| '?'` guard as cmdSend's --to-role path — a prior
  // holder claimed without --to-machine has a null `machine` field.
  const prevStr = prev ? `${prev.machine || '?'}/${prev.session}` : '(no prior holder)';
  console.log(`retired '${role}': ${prevStr} -> ${newHolder.machine || flags['to-machine'] || '?'}/${newHolder.session}  reason: ${flags.reason}`);
  const redirected = out.redirected || [];
  console.log(`  redirected ${redirected.length} recent sender(s): ${redirected.length ? redirected.join(', ') : '(none found)'}`);
}

async function cmdListen(flags) {
  if (!flags.session) {
    console.error('Usage: fleet-bus-client.js listen --session <my-id> [--title "..."]');
    process.exit(1);
  }
  const machine = myMachine();
  for (;;) {
    try {
      const msgs = await request('GET', `/poll?machine=${encodeURIComponent(machine)}&session=${encodeURIComponent(flags.session)}&waitSeconds=25`);
      for (const m of msgs) console.log(frame(m));
    } catch (e) {
      console.error(`[fleet-bus] poll error (${e.message}), retrying in 5s`);
      await new Promise(r => setTimeout(r, 5000));
    }
  }
}

async function cmdSessions() {
  const rows = await request('GET', '/sessions');
  if (!rows.length) return console.log('(no sessions listening)');
  rows.forEach(r => console.log(`${r.machine}/${r.session}  since ${r.since}`));
}

async function cmdHistory(flags) {
  const q = flags.machine ? `?machine=${encodeURIComponent(flags.machine)}` : '';
  const rows = await request('GET', `/messages${q}`);
  if (!rows.length) return console.log('(no messages yet)');
  rows.forEach(m => console.log(`${m.delivered ? 'delivered' : 'queued  '}  ${frame(m)} -> ${m.to}${m.toSession ? '/' + m.toSession : ''}`));
}

const ROLE_COMMANDS = new Set(['claim-role', 'whois', 'retire-role']);

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);

  // Role commands take a positional <role> as their first argument, e.g.
  // `claim-role build-orchestrator --session my-id`. Every other command's
  // args are flags only, so only peel off a positional for these three.
  let role;
  let flagArgs = rest;
  if (ROLE_COMMANDS.has(cmd) && rest[0] && !rest[0].startsWith('--')) {
    role = rest[0];
    flagArgs = rest.slice(1);
  }
  const flags = parseFlags(flagArgs);

  try {
    if (cmd === 'send') await cmdSend(flags);
    else if (cmd === 'listen') await cmdListen(flags);
    else if (cmd === 'sessions') await cmdSessions();
    else if (cmd === 'history') await cmdHistory(flags);
    else if (cmd === 'claim-role') await cmdClaimRole(role, flags);
    else if (cmd === 'whois') await cmdWhois(role);
    else if (cmd === 'retire-role') await cmdRetireRole(role, flags);
    else {
      console.error('Usage: fleet-bus-client.js <send|listen|sessions|history|claim-role|whois|retire-role> [flags]');
      process.exit(1);
    }
  } catch (e) {
    console.error(`[fleet-bus] ${e.message}`);
    process.exit(1);
  }
}

main();
