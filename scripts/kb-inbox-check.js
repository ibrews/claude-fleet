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
    if (content.includes(`target: ${MACHINE_NAME}`) && content.includes('status: pending')) {
      const taskMatch = content.match(/## Task\s*\n([\s\S]*?)(?=\n## |$)/);
      const task = taskMatch ? taskMatch[1].trim().split('\n')[0] : file;
      pendingTriggers.push(task);
    }
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
