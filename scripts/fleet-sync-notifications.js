#!/usr/bin/env node
// fleet-sync-notifications.js — Scheduled task (runs every minute)
// Pulls KB to pick up notifications from other machines.

const { execSync } = require('child_process');

const KB_DIR = require('path').join(process.env.USERPROFILE || process.env.HOME, 'knowledge');

try {
  // Fast-forward pull only — don't rebase or merge, just pick up remote changes
  execSync('git fetch origin master', { cwd: KB_DIR, stdio: 'pipe', timeout: 10000 });
  execSync('git merge --ff-only origin/master', { cwd: KB_DIR, stdio: 'pipe', timeout: 5000 });
} catch {
  // Non-fatal — will retry next minute
}
