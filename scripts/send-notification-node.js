#!/usr/bin/env node
// send-notification.js — Send a notification to another fleet machine.
// Usage: node send-notification.js <target> <subject> <message>
//
// Writes a JSON file to knowledge/notifications/<target>/ and pushes.

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const args = process.argv.slice(2);
if (args.length < 3) {
  console.error('Usage: node send-notification.js <target> <subject> <message>');
  process.exit(1);
}

const [target, subject, ...messageParts] = args;
const message = messageParts.join(' ');

const KB_DIR = path.join(process.env.USERPROFILE || process.env.HOME, 'knowledge');
const NOTIF_DIR = path.join(KB_DIR, 'notifications', target);

// Detect sender dynamically
const MACHINE_NAME = process.env.FLEET_MACHINE_NAME
  || process.env.KB_MACHINE_NAME
  || require('os').hostname().toLowerCase().split('.')[0];

// Create notification dir if needed
fs.mkdirSync(NOTIF_DIR, { recursive: true });

// Write notification
const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
const filename = `${timestamp}.json`;
const filePath = path.join(NOTIF_DIR, filename);

const notification = {
  from: MACHINE_NAME,
  target: target,
  subject: subject,
  message: message,
  timestamp: new Date().toISOString()
};

fs.writeFileSync(filePath, JSON.stringify(notification, null, 2));

// Git add, commit, push
try {
  execSync('git add -A', { cwd: KB_DIR, stdio: 'pipe' });
  execSync(`git commit -m "notify(${target}): ${subject}" --quiet`, { cwd: KB_DIR, stdio: 'pipe' });
  execSync('git pull --rebase origin master --quiet', { cwd: KB_DIR, stdio: 'pipe' });
  execSync('git push origin master --quiet', { cwd: KB_DIR, stdio: 'pipe' });
  console.log(`Notification sent to ${target}: ${subject}`);
} catch (e) {
  console.error('Warning: notification written locally but push may have failed');
}
