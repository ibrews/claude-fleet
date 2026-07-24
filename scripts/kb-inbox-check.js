#!/usr/bin/env node
// kb-inbox-check.js — SessionStart hook
// Pulls KB, reads inbox/<machine>.md, extracts pending items, outputs additionalContext.

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const MACHINE_NAME = process.env.FLEET_MACHINE_NAME
  || process.env.KB_MACHINE_NAME
  || require('os').hostname().toLowerCase().split('.')[0];

const KB_DIR = path.join(process.env.USERPROFILE || process.env.HOME, 'knowledge');
const INBOX = path.join(KB_DIR, 'inbox', `${MACHINE_NAME}.md`);
const TRIGGERS_DIR = path.join(KB_DIR, 'triggers');

try {
  // Pull latest KB
  execSync('git pull --rebase origin master', { cwd: KB_DIR, stdio: 'pipe', timeout: 15000 });
} catch {
  // Non-fatal — continue with local copy
}

let context = '';

// Read inbox
try {
  const inbox = fs.readFileSync(INBOX, 'utf8');
  const pending = [];
  let inPending = false;

  for (const line of inbox.split('\n')) {
    if (line.startsWith('## Pending')) { inPending = true; continue; }
    if (line.startsWith('## ') && inPending) break;
    if (inPending && line.match(/^- \[ \]/)) {
      pending.push(line.replace(/^- \[ \]\s*/, '').trim());
    }
  }

  if (pending.length > 0) {
    context += `INBOX (${pending.length} pending):\n`;
    pending.forEach((item, i) => { context += `  ${i + 1}. ${item}\n`; });
  }
} catch { }

// Check triggers targeting this machine
try {
  const files = fs.readdirSync(TRIGGERS_DIR).filter(f => f.endsWith('.md') && f !== 'README.md');
  const pendingTriggers = [];

  for (const file of files) {
    const content = fs.readFileSync(path.join(TRIGGERS_DIR, file), 'utf8');
    if (!content.includes(`target: ${MACHINE_NAME}`)) continue;

    // Lifecycle states (see docs/05-inbox-system.md § Task lifecycle v2). Matching only
    // 'status: pending' — as this script used to — makes a `review` item silently VANISH from
    // the queue, which is worse than not having the state at all: a session that finishes work
    // and honestly marks it `review` would watch it disappear. `blocked` is the one state we do
    // stay quiet about, deliberately (it's waiting on a human, not on a session).
    const status = (content.match(/^status:\s*(\S+)/m) || [, 'pending'])[1];
    if (!['pending', 'review'].includes(status)) continue;

    const tier = (content.match(/^tier:\s*(\S+)/m) || [])[1];
    const tierLabel = tier ? ` [tier: ${tier}]` : '';
    // done_when is required on new triggers; older ones predate it. Flag on touch rather than
    // bulk-autofilling — a generated placeholder reads as satisfied while meaning nothing.
    const dwLabel = /^done_when:/m.test(content)
      ? ''
      : ' ⚠ no done_when — write one (observable behavior on the real surface) BEFORE starting';
    const reviewLabel = status === 'review'
      ? ' (🔍 NEEDS VERIFICATION: verify done_when on the real surface before marking completed)'
      : '';

    const taskMatch = content.match(/## Task\s*\n([\s\S]*?)(?=\n## |$)/);
    const task = taskMatch ? taskMatch[1].trim().split('\n')[0] : file;
    pendingTriggers.push(`${task}${tierLabel}${reviewLabel}${dwLabel}`);
  }

  if (pendingTriggers.length > 0) {
    context += `\nTRIGGERS (${pendingTriggers.length} pending for ${MACHINE_NAME}):\n`;
    pendingTriggers.forEach((t, i) => { context += `  ${i + 1}. ${t}\n`; });
  }
} catch { }

// Check notifications
const notifDir = path.join(KB_DIR, 'notifications', MACHINE_NAME);
try {
  const notifs = fs.readdirSync(notifDir).filter(f => f.endsWith('.json'));
  if (notifs.length > 0) {
    context += `\nNOTIFICATIONS (${notifs.length} pending):\n`;
    for (const nf of notifs) {
      try {
        const data = JSON.parse(fs.readFileSync(path.join(notifDir, nf), 'utf8'));
        context += `  - [${data.from || 'unknown'}] ${data.subject || 'no subject'}: ${data.message || ''}\n`;
      } catch { }
    }
  }
} catch { }

if (context) {
  const output = { hookSpecificOutput: { additionalContext: context } };
  process.stdout.write(JSON.stringify(output));
}
