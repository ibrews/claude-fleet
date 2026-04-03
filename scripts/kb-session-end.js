#!/usr/bin/env node
// kb-session-end.js — Stop hook
// Commits any KB changes, appends auto-log entry if daily log wasn't touched, pushes.

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

const KB_DIR = path.join(process.env.USERPROFILE || process.env.HOME, 'knowledge');

// Detect machine name
function getMachine() {
  const h = os.hostname().toLowerCase();
  if (h.includes('fortress') || h.includes('fort')) return 'fort';
  if (h.includes('fridge') || h.includes('archie')) return 'archie';
  if (h.includes('macbookpro') || h.includes('alexs-macbook')) return 'alex-mbp';
  if (h.includes('mac-mini') || h.startsWith('sam')) return 'sam';
  if (h.includes('lenovo')) return 'lenovo';
  if (h.includes('toaster')) return 'toaster';
  if (h.includes('theseus')) return 'theseus';
  return h;
}

function run(cmd) {
  return execSync(cmd, { cwd: KB_DIR, stdio: 'pipe', timeout: 15000 }).toString().trim();
}

try {
  // Check for changes
  const status = run('git status --porcelain');
  if (!status) process.exit(0);

  const machine = getMachine();
  const today = new Date().toISOString().slice(0, 10);
  const time = new Date().toTimeString().slice(0, 5);
  const dailyLog = path.join(KB_DIR, 'daily', `${today}-${machine}.md`);

  // Stage everything
  run('git add -A');

  // Check if daily log was touched
  let dailyTouched = false;
  try {
    const cached = run('git diff --cached --name-only');
    dailyTouched = cached.includes(`daily/${today}-${machine}.md`);
  } catch { }

  // Auto-log if daily wasn't updated
  if (!dailyTouched) {
    const changedFiles = run('git diff --cached --name-only').split('\n').filter(Boolean);
    const fileCount = changedFiles.length;

    if (!fs.existsSync(dailyLog)) {
      const header = `---\ntitle: "Daily Log — ${today} (${machine})"\nupdated: ${today}\nmachine: ${machine}\ntags: [daily]\n---\n# Daily Log — ${today} (${machine})\n\n## Sessions\n`;
      fs.writeFileSync(dailyLog, header);
    }

    let entry = `\n### Auto-logged — ${machine} @ ${time}\nKB files modified (${fileCount} files):\n`;
    changedFiles.slice(0, 10).forEach(f => { entry += `- \`${f}\`\n`; });
    fs.appendFileSync(dailyLog, entry);
    run(`git add "${dailyLog}"`);
  }

  // Commit
  const timestamp = new Date().toTimeString().slice(0, 5).replace(':', '');
  try {
    run(`git commit -m "chore(kb): auto-sync from ${machine} session-end ${today}-${timestamp}" --quiet`);
  } catch { }

  // Pull and push
  try { run('git pull --rebase origin master --quiet'); } catch { }
  try { run('git push origin master --quiet'); } catch { }
} catch {
  // Don't fail the hook
}
