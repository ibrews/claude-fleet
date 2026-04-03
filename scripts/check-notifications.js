#!/usr/bin/env node
// check-notifications.js — PostToolUse hook
// Checks for pending notification files, injects them as additionalContext.

const fs = require('fs');
const path = require('path');

const NOTIF_DIR = path.join(process.env.USERPROFILE || process.env.HOME, 'knowledge', 'notifications', 'fort');

try {
  if (!fs.existsSync(NOTIF_DIR)) process.exit(0);

  const files = fs.readdirSync(NOTIF_DIR).filter(f => f.endsWith('.json'));
  if (files.length === 0) process.exit(0);

  let context = `FLEET NOTIFICATIONS (${files.length}):\n`;

  for (const file of files) {
    const filePath = path.join(NOTIF_DIR, file);
    try {
      const data = JSON.parse(fs.readFileSync(filePath, 'utf8'));
      context += `- [${data.from || 'unknown'}] ${data.subject || 'no subject'}: ${data.message || ''}\n`;
      // Delete after reading
      fs.unlinkSync(filePath);
    } catch {
      // Skip malformed files
    }
  }

  const output = { hookSpecificOutput: { additionalContext: context } };
  process.stdout.write(JSON.stringify(output));
} catch {
  // Don't fail the hook
}
