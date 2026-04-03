#!/usr/bin/env node
/**
 * Send a fleet notification to another machine.
 * Usage: node send-notification.js <target> <subject> <message> [priority]
 *
 * Example:
 *   node send-notification.js alpha "Build complete" "Built v1.2.0, uploaded to TestFlight" normal
 *
 * Works on macOS, Linux, and Windows (no bash dependency).
 */
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

const [,, target, subject, message, priority = 'normal'] = process.argv;

if (!target || !subject) {
    console.error('Usage: node send-notification.js <target> <subject> <message> [priority]');
    console.error('  priority: "normal" (default) or "urgent"');
    process.exit(1);
}

// Detect sender machine name from hostname (override with FLEET_MACHINE_NAME env var)
const from = process.env.FLEET_MACHINE_NAME || os.hostname().toLowerCase().split('.')[0];

// KB path
const kbDir = path.join(os.homedir(), 'knowledge');
const notifDir = path.join(kbDir, 'notifications', target);

// Create notification file
const timestamp = new Date().toISOString();
const slug = subject.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40);
const filename = `${timestamp.replace(/[:.]/g, '').slice(0, 15)}-${slug}.json`;

fs.mkdirSync(notifDir, { recursive: true });
fs.writeFileSync(path.join(notifDir, filename), JSON.stringify({
    from,
    to: target,
    subject,
    message: message || '',
    timestamp,
    priority
}, null, 2));

// Git add, commit, push
try {
    const relPath = path.join('notifications', target, filename);
    execSync(`git add "${relPath}"`, { cwd: kbDir, stdio: 'pipe' });
    const safeSubject = subject.replace(/["`$\\!&|;]/g, '').slice(0, 80);
    execSync(`git commit -m "notify(${target}): ${safeSubject}" --quiet`, { cwd: kbDir, stdio: 'pipe' });
    execSync('git push origin HEAD --quiet', { cwd: kbDir, stdio: 'pipe' });
    console.log(`📬 Notification sent to ${target}: ${subject}`);
} catch (err) {
    // Pull-rebase and retry if push failed (concurrent KB edits)
    try {
        execSync('git pull --rebase origin master --quiet', { cwd: kbDir, stdio: 'pipe' });
        execSync('git push origin HEAD --quiet', { cwd: kbDir, stdio: 'pipe' });
        console.log(`📬 Notification sent to ${target}: ${subject} (after rebase)`);
    } catch (e) {
        console.error(`Failed to push notification: ${e.message}`);
        process.exit(1);
    }
}
