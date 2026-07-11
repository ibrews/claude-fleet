#!/usr/bin/env node
// check-notifications.js — PostToolUse hook
// Checks for pending notification files, injects them as additionalContext,
// then removes them from the shared KB (git rm + commit + push) so they don't
// get redelivered and match the "deleted after delivery" contract in
// notifications/README.md.
//
// Fixed 2026-07-10: the original version deleted consumed files locally but
// never committed+pushed the deletion, so a "delivered" notification would
// never actually leave the shared repo (a "notification" from any other
// machine would show up once, correctly, but then silently linger forever on
// origin instead of being cleaned up). Found + fixed on a real fleet
// deployment where the fetch/cron half had been running fine for months while
// this consumer half sat unregistered in settings.json the whole time.

const fs = require('fs');
const path = require('path');
const os = require('os');
const { execSync } = require('child_process');

// Resolve the machine name the same way notify-human.js does: env var first,
// then a local fleet.env file, then hostname as a last resort. The file
// fallback matters in practice -- a machine's actual hostname often doesn't
// match its short fleet name (e.g. hostname "FORTRESS" vs fleet name "fort"),
// and FLEET_MACHINE_NAME as a plain *exported* env var doesn't reliably reach
// every process that launches this hook (a fresh scheduled task, a Claude
// Code session started before a setx took effect, etc.) -- silently falling
// back to the wrong hostname-derived directory means notifications land
// somewhere this hook never looks. Found live: this exact failure mode, on a
// real deployment, the first time this file switched from a hardcoded
// machine name to the env-var pattern.
function resolveMachineName() {
  let name = process.env.FLEET_MACHINE_NAME || process.env.KB_MACHINE_NAME || '';
  if (!name) {
    for (const p of [path.join(os.homedir(), 'claude-fleet', 'fleet.env'), path.join(os.homedir(), '.claude', 'fleet.env')]) {
      try {
        const m = fs.readFileSync(p, 'utf8').match(/FLEET_MACHINE_NAME=(.+)/);
        if (m) { name = m[1].trim(); break; }
      } catch {}
    }
  }
  return name || os.hostname().toLowerCase().split('.')[0];
}

const MACHINE_NAME = resolveMachineName();
const KB_DIR = path.join(process.env.USERPROFILE || process.env.HOME, 'knowledge');
const NOTIF_DIR = path.join(KB_DIR, 'notifications', MACHINE_NAME);

try {
  if (!fs.existsSync(NOTIF_DIR)) process.exit(0);

  const files = fs.readdirSync(NOTIF_DIR).filter(f => f.endsWith('.json'));
  if (files.length === 0) process.exit(0);

  let context = `FLEET NOTIFICATIONS (${files.length}):\n`;
  const consumed = [];

  for (const file of files) {
    const filePath = path.join(NOTIF_DIR, file);
    try {
      const data = JSON.parse(fs.readFileSync(filePath, 'utf8'));
      context += `- [${data.from || 'unknown'}] ${data.subject || 'no subject'}: ${data.message || ''}\n`;
      fs.unlinkSync(filePath);
      consumed.push(path.join('notifications', MACHINE_NAME, file));
    } catch {
      // Skip malformed files -- leave them for manual triage rather than silently eating them
    }
  }

  if (consumed.length > 0) {
    try {
      // Scoped `git rm` on the exact consumed paths only -- NOT `git add -A`,
      // so this never sweeps up unrelated uncommitted work sitting in the KB
      // checkout at the time the hook happens to fire.
      execSync(`git rm --quiet -- ${consumed.map(p => `"${p}"`).join(' ')}`, { cwd: KB_DIR, stdio: 'pipe', timeout: 8000 });
      execSync(`git commit --quiet -m "chore(notifications): delivered to ${MACHINE_NAME} (${consumed.length})"`, { cwd: KB_DIR, stdio: 'pipe', timeout: 8000 });
      execSync('git pull --rebase --quiet origin master', { cwd: KB_DIR, stdio: 'pipe', timeout: 10000 });
      execSync('git push --quiet origin master', { cwd: KB_DIR, stdio: 'pipe', timeout: 10000 });
    } catch {
      // Best-effort cleanup -- delivery to the user already happened via
      // additionalContext below; a failed push just means the file may
      // resurface once on the next fetch (self-healing, not a hard failure).
    }
  }

  const output = { hookSpecificOutput: { additionalContext: context } };
  process.stdout.write(JSON.stringify(output));
} catch {
  // Don't fail the hook
}
