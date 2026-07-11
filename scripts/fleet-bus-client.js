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
  if (!flags.to || !flags.body) {
    console.error('Usage: fleet-bus-client.js send --to <machine> --body "<text>" [--to-session <id>] [--session <my-id>]');
    process.exit(1);
  }
  const out = await request('POST', '/send', {
    token: true,
    body: {
      to: flags.to, from: myMachine(),
      to_session: flags['to-session'], from_session: flags.session,
      body: flags.body,
    },
  });
  console.log(`#${out.id} ${out.delivered_live ? 'delivered live' : 'queued (no live listener — delivers on next listen)'}`);
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

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  const flags = parseFlags(rest);
  try {
    if (cmd === 'send') await cmdSend(flags);
    else if (cmd === 'listen') await cmdListen(flags);
    else if (cmd === 'sessions') await cmdSessions();
    else if (cmd === 'history') await cmdHistory(flags);
    else {
      console.error('Usage: fleet-bus-client.js <send|listen|sessions> [flags]');
      process.exit(1);
    }
  } catch (e) {
    console.error(`[fleet-bus] ${e.message}`);
    process.exit(1);
  }
}

main();
