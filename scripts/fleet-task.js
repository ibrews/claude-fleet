#!/usr/bin/env node
// fleet-task.js — Dispatch a headless Claude Code task to a fleet machine via SSH.
//
// Usage:
//   node fleet-task.js <machine> "<prompt>" [options]
//
// Options:
//   --tools "Read,Bash,Glob"   Comma-separated allowed tools (default: all)
//   --json                     Output as JSON (default: text)
//   --model <model>            Override model (e.g., claude-sonnet-4-6)
//   --bare                     Skip hooks/skills for faster startup
//   --timeout <seconds>        SSH timeout (default: 300)
//   --bg                       Fire and forget (don't wait for result)
//
// Machine configuration:
//   Reads from ~/.claude-fleet/machines.json if it exists, otherwise uses
//   FLEET_MACHINES env var (JSON string), e.g.:
//     export FLEET_MACHINES='{"mybox":{"host":"mybox","ip":"10.0.0.1","os":"linux"}}'
//
// machines.json format:
//   {
//     "machine-name": { "host": "ssh-alias", "ip": "10.0.0.1", "os": "linux|macos|windows" },
//     ...
//   }
//
// Examples:
//   node fleet-task.js mybox "Find all TODO comments in the project"
//   node fleet-task.js server "Summarize this file" --tools "Read,Glob" --json

const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

// Load fleet machines from config file or env var
function loadMachines() {
  // Try ~/.claude-fleet/machines.json first
  const configPath = path.join(process.env.USERPROFILE || process.env.HOME, '.claude-fleet', 'machines.json');
  if (fs.existsSync(configPath)) {
    try {
      return JSON.parse(fs.readFileSync(configPath, 'utf8'));
    } catch (e) {
      console.error(`[fleet-task] Error reading ${configPath}: ${e.message}`);
      process.exit(1);
    }
  }

  // Try FLEET_MACHINES env var
  if (process.env.FLEET_MACHINES) {
    try {
      return JSON.parse(process.env.FLEET_MACHINES);
    } catch (e) {
      console.error(`[fleet-task] Error parsing FLEET_MACHINES env var: ${e.message}`);
      process.exit(1);
    }
  }

  console.error('[fleet-task] No machines configured.');
  console.error('  Create ~/.claude-fleet/machines.json with your fleet machines, e.g.:');
  console.error('  {');
  console.error('    "mybox": { "host": "mybox", "ip": "10.0.0.1", "os": "linux" }');
  console.error('  }');
  console.error('  Or set FLEET_MACHINES env var to a JSON string with the same format.');
  process.exit(1);
}

const MACHINES = loadMachines();

function usage() {
  console.error('Usage: node fleet-task.js <machine> "<prompt>" [--tools T] [--json] [--model M] [--bare] [--timeout S] [--bg]');
  console.error(`\nMachines: ${Object.keys(MACHINES).join(', ')}`);
  process.exit(1);
}

function parseArgs(argv) {
  const args = argv.slice(2);
  if (args.length < 2) usage();

  const machine = args[0].toLowerCase();
  if (!MACHINES[machine]) {
    console.error(`Unknown machine: ${machine}\nAvailable: ${Object.keys(MACHINES).join(', ')}`);
    process.exit(1);
  }

  // Find the prompt (first non-flag arg after machine)
  let prompt = '';
  let i = 1;
  if (!args[1].startsWith('--')) {
    prompt = args[1];
    i = 2;
  }

  const opts = {
    machine: MACHINES[machine],
    machineName: machine,
    prompt,
    tools: '',
    json: false,
    model: '',
    bare: false,
    timeout: 300,
    bg: false,
  };

  for (; i < args.length; i++) {
    switch (args[i]) {
      case '--tools': opts.tools = args[++i]; break;
      case '--json': opts.json = true; break;
      case '--model': opts.model = args[++i]; break;
      case '--bare': opts.bare = true; break;
      case '--timeout': opts.timeout = parseInt(args[++i], 10); break;
      case '--bg': opts.bg = true; break;
      default:
        if (!opts.prompt) opts.prompt = args[i];
        break;
    }
  }

  if (!opts.prompt) usage();
  return opts;
}

function buildClaudeCmd(opts) {
  const isWindows = opts.machine.os === 'windows';

  let cmd;
  if (isWindows) {
    // Windows SSH needs double quotes; escape inner doubles
    const escaped = opts.prompt.replace(/"/g, '\\"');
    cmd = `claude -p "${escaped}"`;
  } else {
    // macOS/Linux: single quotes, escape inner singles
    const escaped = opts.prompt.replace(/'/g, "'\\''");
    cmd = `claude -p '${escaped}'`;
  }

  if (opts.json) cmd += ' --output-format json';
  if (opts.tools) {
    // Validate tools against whitelist: only alphanumeric, commas, spaces, hyphens, underscores
    if (!/^[a-zA-Z0-9,\s_-]+$/.test(opts.tools)) {
      console.error(`[fleet-task] Invalid --tools value: contains disallowed characters.`);
      console.error(`[fleet-task] Only alphanumeric characters, commas, spaces, hyphens, and underscores are allowed.`);
      process.exit(1);
    }
    // Reject shell metacharacters explicitly as a defense-in-depth check
    if (/[;|&`$(){}!<>?*\[\]\\]/.test(opts.tools)) {
      console.error(`[fleet-task] Rejected --tools value: shell metacharacters detected.`);
      process.exit(1);
    }
    cmd += ` --allowedTools "${opts.tools}"`;
  }
  if (opts.model) cmd += ` --model "${opts.model}"`;
  if (opts.bare) cmd += ' --bare';

  return cmd;
}

function main() {
  const opts = parseArgs(process.argv);
  const claudeCmd = buildClaudeCmd(opts);
  const sshHost = opts.machine.host;

  console.error(`[fleet-task] Dispatching to ${opts.machineName} (${sshHost})...`);
  console.error(`[fleet-task] Command: ${claudeCmd}`);

  const sshArgs = [
    '-o', 'ConnectTimeout=10',
    '-o', `ServerAliveInterval=30`,
    sshHost,
    claudeCmd,
  ];

  if (opts.bg) {
    // Fire and forget — nohup + background on remote
    const bgCmd = `nohup ${claudeCmd} > /tmp/fleet-task-${Date.now()}.log 2>&1 &`;
    const proc = spawn('ssh', ['-o', 'ConnectTimeout=10', sshHost, bgCmd], {
      stdio: 'inherit',
    });
    proc.on('close', (code) => {
      console.error(`[fleet-task] Task dispatched to ${opts.machineName} (background)`);
      process.exit(0);
    });
    return;
  }

  const proc = spawn('ssh', sshArgs, {
    stdio: ['ignore', 'pipe', 'pipe'],
    timeout: opts.timeout * 1000,
  });

  let stdout = '';
  let stderr = '';

  proc.stdout.on('data', (chunk) => {
    const text = chunk.toString();
    stdout += text;
    process.stdout.write(text);
  });

  proc.stderr.on('data', (chunk) => {
    const text = chunk.toString();
    stderr += text;
    process.stderr.write(text);
  });

  proc.on('close', (code) => {
    if (code !== 0) {
      console.error(`\n[fleet-task] ${opts.machineName} exited with code ${code}`);
      if (stderr.includes('command not found') || stderr.includes('not recognized')) {
        console.error(`[fleet-task] Claude CLI not found on ${opts.machineName}. Install with: npm install -g @anthropic-ai/claude-code`);
      }
    }
    process.exit(code || 0);
  });

  proc.on('error', (err) => {
    console.error(`[fleet-task] SSH error: ${err.message}`);
    process.exit(1);
  });
}

main();
