#!/usr/bin/env node
// fleet-bot — Telegram relay for a Claude Code fleet.
//
// Runs on the always-on gateway machine. Long-polls Telegram. Jobs:
//
//   1. Handle callback-query button presses from turn-guard warnings.
//        s:<machine>:<sid>  → SSH to <machine>, touch /tmp/tg-<sid>.stop
//        u:<machine>:<sid>  → SSH to <machine>, write /tmp/tg-<sid>.max = curCount + 250
//        k:<machine>:<sid>  → SSH to <machine>, resume session with "Great, keep going!"
//
//   2. Handle text replies-to-message. Turn-guard messages (and the session
//      bus's `--to human` relay — see scripts/fleet-bus-server.js) carry
//      trailing `#sid=<uuid> #machine=<hostname>` tags. On reply: if that
//      session currently has a LIVE fleet-bus listener, route the reply
//      through the bus instead (instant, works cross-platform including
//      Windows — SSH `claude --resume` below can't reach Windows machines).
//      Otherwise fall back to `claude --resume <sid> -p "<text>"` over SSH.
//
//   3. Direct commands (no reply needed): /sessions (who's listening on the
//      bus, fleet-wide), /msg <machine> <text> (bus-message any machine).
//
// Config:
//   ~/claude-fleet/fleet.env              TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
//   telegram/fleet-bot/machines.json      { hostname: { host, user } }  (Tailscale map)
//   FLEET_BUS_URL / FLEET_BUS_TOKEN env   optional — only needed for bus-aware
//                                          routing (2) and commands (3). Without
//                                          it fleet-bot still works as before
//                                          (turn-guard buttons + SSH resume).

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import http from 'node:http';
import { fileURLToPath } from 'node:url';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { Bot } from 'grammy';

const execFileP = promisify(execFile);
const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ---------- config ----------

const ENV_FILE = path.join(os.homedir(), 'claude-fleet', 'fleet.env');
if (fs.existsSync(ENV_FILE)) {
    for (const line of fs.readFileSync(ENV_FILE, 'utf8').split('\n')) {
        const m = line.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$/);
        if (m) process.env[m[1]] = m[2].replace(/^["']|["']$/g, '');
    }
}
const TOKEN   = process.env.TELEGRAM_BOT_TOKEN;
const CHAT_ID = process.env.TELEGRAM_CHAT_ID;
if (!TOKEN)   { console.error('TELEGRAM_BOT_TOKEN missing'); process.exit(1); }
if (!CHAT_ID) { console.error('TELEGRAM_CHAT_ID missing');   process.exit(1); }

const MACHINES_FILE = path.join(__dirname, 'machines.json');
if (!fs.existsSync(MACHINES_FILE)) {
    console.error(`machines.json missing — copy machines.example.json to machines.json and edit.`);
    process.exit(1);
}
const MACHINES = JSON.parse(fs.readFileSync(MACHINES_FILE, 'utf8'));

const FCC_URL = process.env.FLEET_BUS_URL || 'http://localhost:4100';
const FCC_TOKEN = process.env.FLEET_BUS_TOKEN || '';

// ---------- fleet session bus helpers (optional — see header comment) ----------

function busApi(method, urlPath, body) {
    return new Promise((resolve, reject) => {
        const data = body ? JSON.stringify(body) : null;
        const headers = { 'Content-Type': 'application/json' };
        if (data) headers['X-Fleet-Token'] = FCC_TOKEN;
        const req = http.request(FCC_URL + urlPath, { method, headers, timeout: 8000 }, (res) => {
            let raw = '';
            res.on('data', c => raw += c);
            res.on('end', () => {
                let parsed;
                try { parsed = JSON.parse(raw); } catch (e) { return reject(new Error(`bad bus response: ${raw.slice(0, 200)}`)); }
                if (res.statusCode >= 400) return reject(new Error(parsed.error || `bus HTTP ${res.statusCode}`));
                resolve(parsed);
            });
        });
        req.on('timeout', () => req.destroy(new Error('bus request timed out')));
        req.on('error', reject);
        if (data) req.write(data);
        req.end();
    });
}

async function isListeningOnBus(machine, sid) {
    try {
        const rows = await busApi('GET', '/sessions');
        return rows.some(r => r.machine === machine.toLowerCase() && r.session === sid);
    } catch (e) {
        return false; // bus unreachable — fall back to SSH resume, don't block on it
    }
}

async function busSend(to, to_session, text) {
    return busApi('POST', '/send', { to, to_session, from: 'human', body: text });
}

// ---------- ssh helpers ----------

function machineEndpoint(name) {
    const m = MACHINES[name];
    if (!m) throw new Error(`Unknown machine: ${name}. Add it to machines.json.`);
    return m;
}

// Run a shell command on a target machine. If host=localhost, run locally.
async function runOnMachine(machine, shellCommand) {
    const ep = machineEndpoint(machine);
    if (ep.host === 'localhost' || ep.host === '127.0.0.1') {
        return execFileP('bash', ['-lc', shellCommand], { timeout: 30_000 });
    }
    return execFileP('ssh', [
        '-o', 'BatchMode=yes',
        '-o', 'ConnectTimeout=5',
        '-o', 'StrictHostKeyChecking=accept-new',
        `${ep.user}@${ep.host}`,
        shellCommand,
    ], { timeout: 30_000 });
}

function shQuote(s) {
    return `'${String(s).replace(/'/g, `'\\''`)}'`;
}

// ---------- actions ----------

async function actionStop(machine, sid) {
    const sidSafe = sid.replace(/[^a-zA-Z0-9_-]/g, '');
    await runOnMachine(machine, `touch /tmp/tg-${sidSafe}.stop`);
    return `Stop requested on ${machine} for ${sid.slice(0, 8)}. Next tool call will block.`;
}

async function actionUnrestrict(machine, sid, addTurns = 250) {
    const sidSafe = sid.replace(/[^a-zA-Z0-9_-]/g, '');
    // New cap = current count + addTurns (so you get at least addTurns more turns).
    const cmd = `cur=$(cat /tmp/tg-${sidSafe} 2>/dev/null || echo 0); new=$((cur + ${addTurns})); echo $new > /tmp/tg-${sidSafe}.max; echo $new`;
    const { stdout } = await runOnMachine(machine, cmd);
    const newMax = stdout.trim();
    return `Unrestricted on ${machine}: cap raised to ${newMax} turns for ${sid.slice(0, 8)}.`;
}

// How recent counts as "live" — if the transcript JSONL was written within this
// many seconds, we assume a claude process still owns it and queue the message
// to /tmp/tg-queue-<sid>.txt instead of racing a parallel `claude --resume`.
const LIVE_WINDOW_SECS = 30;

async function actionResume(machine, sid, message) {
    const sidSafe = sid.replace(/[^a-zA-Z0-9_-]/g, '');
    const queueFile = `/tmp/tg-queue-${sidSafe}.txt`;
    const script = [
        `transcript=$(ls -t "$HOME"/.claude/projects/*/${shQuote(sidSafe)}.jsonl 2>/dev/null | head -1)`,
        `now=$(date +%s)`,
        `if [ -n "$transcript" ]; then`,
        `  mtime=$(stat -f %m "$transcript" 2>/dev/null || stat -c %Y "$transcript" 2>/dev/null || echo 0)`,
        `  age=$((now - mtime))`,
        `  if [ "$age" -lt ${LIVE_WINDOW_SECS} ]; then`,
        `    printf "%s\\n" ${shQuote(message)} >> ${shQuote(queueFile)}`,
        `    echo "QUEUED age=$age"`,
        `    exit 0`,
        `  fi`,
        `fi`,
        `nohup claude --resume ${shQuote(sidSafe)} -p ${shQuote(message)} >/tmp/tg-resume-${sidSafe}.log 2>&1 </dev/null &`,
        `echo "RESUMED pid=$!"`,
    ].join('; ');
    try {
        const { stdout } = await runOnMachine(machine, script);
        const out = stdout.trim();
        if (out.startsWith('QUEUED')) {
            return `Session ${sid.slice(0, 8)} on ${machine} is live — queued to ${queueFile} (${out}).`;
        }
        return `Resumed ${sid.slice(0, 8)} on ${machine} (${out}).`;
    } catch (err) {
        return `Failed to resume on ${machine}: ${err.message}`;
    }
}

// Prefer the live bus (instant, cross-platform) when the target session is
// currently listening; else fall back to the original SSH `claude --resume`
// path (POSIX-only, works on a stopped session).
async function routeReply(machine, sid, text) {
    if (await isListeningOnBus(machine, sid)) {
        try {
            await busSend(machine, sid, text);
            return `Delivered live via the fleet bus to ${sid.slice(0, 8)} on ${machine} (session is actively listening).`;
        } catch (err) {
            // bus send failed even though the session showed as listening — fall through to resume
        }
    }
    return actionResume(machine, sid, text);
}

// ---------- bot ----------

const bot = new Bot(TOKEN);

bot.on('callback_query:data', async (ctx) => {
    const data = ctx.callbackQuery.data || '';
    const parts = data.split(':');
    const [action, machine, ...sidParts] = parts;
    const sid = sidParts.join(':');
    if (!action || !machine || !sid) {
        await ctx.answerCallbackQuery({ text: 'Malformed callback', show_alert: false });
        return;
    }
    try {
        let result;
        if (action === 's')      result = await actionStop(machine, sid);
        else if (action === 'u') result = await actionUnrestrict(machine, sid);
        else if (action === 'k') result = await routeReply(machine, sid, 'Great, keep going!');
        else {
            await ctx.answerCallbackQuery({ text: `Unknown action: ${action}` });
            return;
        }
        await ctx.answerCallbackQuery({ text: result.slice(0, 200) });
        await ctx.reply(`✅ ${result}`, { reply_parameters: { message_id: ctx.callbackQuery.message?.message_id || 0, allow_sending_without_reply: true } });
    } catch (err) {
        console.error('callback error', err);
        await ctx.answerCallbackQuery({ text: `Error: ${err.message}`.slice(0, 200), show_alert: true });
    }
});

// Parse trailing "#sid=... #machine=..." tags from a message.
function parseTagsFromMessage(msg) {
    const text = msg?.text || msg?.caption || '';
    const sid = text.match(/#sid=([A-Za-z0-9_-]+)/)?.[1];
    const machine = text.match(/#machine=([A-Za-z0-9_.-]+)/)?.[1];
    if (sid && machine) return { sid, machine };
    return null;
}

bot.on('message:text', async (ctx) => {
    if (String(ctx.chat.id) !== String(CHAT_ID)) return;
    const text = ctx.message.text;
    const replied = ctx.message.reply_to_message;

    if (!replied) {
        if (text === '/ping') { await ctx.reply('pong'); return; }

        if (text === '/sessions') {
            try {
                const rows = await busApi('GET', '/sessions');
                if (!rows.length) { await ctx.reply('No sessions currently listening on the fleet bus.'); return; }
                const lines = rows.map(r => `• ${r.machine}/${r.session} (since ${r.since})`);
                await ctx.reply(`🟢 Listening now:\n${lines.join('\n')}`);
            } catch (err) {
                await ctx.reply(`Error fetching sessions (is fleet-bus-server.js running? see FLEET_BUS_URL): ${err.message}`);
            }
            return;
        }

        const msgMatch = text.match(/^\/msg\s+(\S+)\s+([\s\S]+)$/);
        if (msgMatch) {
            const [, machine, body] = msgMatch;
            try {
                const out = await busSend(machine.toLowerCase(), null, body);
                await ctx.reply(out.delivered_live ? `✅ Delivered live to ${machine}.` : `📬 Queued for ${machine} (no live listener right now).`);
            } catch (err) {
                await ctx.reply(`Error sending to ${machine}: ${err.message}`);
            }
            return;
        }

        return;
    }

    const entry = parseTagsFromMessage(replied);
    if (!entry) {
        await ctx.reply(`Can't route this reply — no #sid tag on the original message.`);
        return;
    }
    try {
        const result = await routeReply(entry.machine, entry.sid, text);
        await ctx.reply(`📨 ${result}`);
    } catch (err) {
        await ctx.reply(`Error routing reply: ${err.message}`);
    }
});

bot.catch((err) => { console.error('Bot error:', err); });

console.log(`[fleet-bot] starting, chat_id=${CHAT_ID}, machines=${Object.keys(MACHINES).join(',')}`);
bot.start({
    drop_pending_updates: true,
    onStart: (me) => console.log(`[fleet-bot] connected as @${me.username}`),
});
