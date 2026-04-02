#!/usr/bin/env node
// Claude Code Stop Hook: Telegram notification on task completion
//
// Sends a Telegram message when Claude finishes a task, with status icons:
//   ✅ — completed successfully
//   ❌ — error detected in response
//   ⚠️ — hit the turn limit (may need re-running)
//   🔔 — needs human decision or input
//
// Zero npm dependencies — uses only Node.js builtins.
//
// Install:
//   1. Copy to ~/claude-fleet/notify-human.js
//   2. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in ~/claude-fleet/fleet.env
//   3. Add to ~/.claude/settings.json under hooks.Stop:
//      { "type": "command", "command": "node $HOME/claude-fleet/notify-human.js", "timeout": 10 }

const https = require('https');
const os = require('os');
const fs = require('fs');
const path = require('path');

// Load config from environment or .env file
function loadConfig() {
  let token = process.env.TELEGRAM_BOT_TOKEN || '';
  let chatId = process.env.TELEGRAM_CHAT_ID || '';

  if (!token || !chatId) {
    // Try loading from fleet.env or .ccgram/.env
    const envPaths = [
      path.join(os.homedir(), 'claude-fleet', 'fleet.env'),
      path.join(os.homedir(), '.claude', 'fleet.env'),  // legacy fallback
      path.join(os.homedir(), '.ccgram', '.env'),
    ];
    for (const p of envPaths) {
      try {
        const content = fs.readFileSync(p, 'utf8');
        if (!token) {
          const m = content.match(/TELEGRAM_BOT_TOKEN=(.+)/);
          if (m) token = m[1].trim();
        }
        if (!chatId) {
          const m = content.match(/TELEGRAM_CHAT_ID=(.+)/);
          if (m) chatId = m[1].trim();
        }
      } catch {}
    }
  }

  return { token, chatId };
}

// Detect machine name from hostname
// Customize this mapping for your fleet
function getMachine() {
  const name = process.env.FLEET_MACHINE_NAME;
  if (name) return name;

  const h = os.hostname().toLowerCase();

  // Add your hostname mappings here, e.g.:
  // if (h.includes('macbook')) return 'laptop';
  // if (h.includes('server')) return 'server';
  // if (h.includes('desktop')) return 'desktop';

  return h;
}

function sendTelegram(token, chatId, text) {
  return new Promise((resolve) => {
    const data = JSON.stringify({
      chat_id: chatId,
      parse_mode: 'HTML',
      text: text,
      disable_web_page_preview: true
    });
    const req = https.request({
      hostname: 'api.telegram.org',
      path: `/bot${token}/sendMessage`,
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) }
    }, (res) => {
      res.on('data', () => {});
      res.on('end', () => resolve());
    });
    req.on('error', () => resolve());
    req.write(data);
    req.end();
  });
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

async function main() {
  const { token, chatId } = loadConfig();
  if (!token || !chatId) {
    process.exit(0); // No Telegram config — skip silently
  }

  // Read the Stop hook payload from stdin
  let input = '';
  try {
    input = fs.readFileSync(0, 'utf8');
  } catch {}

  let data = {};
  try { data = JSON.parse(input); } catch {}

  const stopReason = data.stopReason || 'unknown';

  // Only notify on reasons that suggest the task is done and waiting for human
  if (!['end_turn', 'max_turns', 'stop_button'].includes(stopReason)) {
    process.exit(0);
  }

  // Extract summary from response
  let summary = data.responseText || data.response || '(no summary available)';
  if (summary.length > 300) {
    summary = '...' + summary.slice(-300);
    const nl = summary.indexOf('\n', 3);
    if (nl > 0 && nl < 50) summary = '...' + summary.slice(nl + 1);
  }
  summary = escapeHtml(summary);

  // Pick status icon based on stop reason and content
  let icon = '✅';
  const lower = summary.toLowerCase();
  if (stopReason === 'max_turns') {
    icon = '⚠️';
  } else if (lower.includes('error') || lower.includes('failed') || lower.includes('fatal') || lower.includes('crash') || lower.includes('cannot') || lower.includes('unable to')) {
    icon = '❌';
  } else if (lower.includes('blocked') || lower.includes('needs human') || lower.includes('needs your') || lower.includes('decision') || lower.includes('manual')) {
    icon = '🔔';
  }

  const machine = getMachine();
  const reason = stopReason === 'max_turns' ? ' (hit turn limit)' : '';
  const msg = `${icon} <b>${machine}</b>${reason}\n\n<i>${summary}</i>`;

  await sendTelegram(token, chatId, msg);
}

main().catch(() => {}).then(() => process.exit(0));
