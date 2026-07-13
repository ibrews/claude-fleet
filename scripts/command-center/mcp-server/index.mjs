#!/usr/bin/env node
/**
 * Command Center — MCP Server (PRIMARY master surface)
 *
 * Lets the operator talk to the Command Center orchestrator from Claude Desktop:
 * "what's the state of your-project?", "spawn a worker to do X", "confirm that",
 * "halt everything". One master brain, three windows — this is the primary
 * window; Telegram (mobile pings) + the FCC dashboard (glance) are secondary.
 *
 * THIN PROXY by design: this server runs wherever Claude Desktop runs (the operator's
 * Mac). It does NOT launch or reap workers locally — that must happen on the
 * single-writer host (Alpha), co-located with the always-on loop, because reap
 * uses local pid liveness. So every state-changing tool POSTs to the Command
 * Center control agent (command_center_server.py) on Alpha over the tailnet,
 * token-gated with the same ~/.fleet-token as the bus. Reads go the same way;
 * read_transcript reuses the Fleet Transcript Agent via fleet_bus.py.
 *
 * Setup — add to claude_desktop_config.json (see README):
 *   "command-center": {
 *     "command": "node",
 *     "args": ["/Users/you/knowledge/departments/engineering/command-center/mcp-server/index.mjs"]
 *   }
 * Env: CC_AGENT_URL (default http://100.64.0.1:3838, Alpha's tailnet IP),
 *      FLEET_TOKEN (else ~/.fleet-token), CC_KB_ROOT (default ~/knowledge),
 *      CC_DEFAULT_INSTANCE (default your-project).
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { readFileSync, existsSync } from "fs";
import { execFile } from "child_process";
import { homedir } from "os";
import { join } from "path";

const AGENT_URL = process.env.CC_AGENT_URL || "http://100.64.0.1:3838";
const KB_ROOT = process.env.CC_KB_ROOT || join(homedir(), "knowledge");
const DEFAULT_INSTANCE = process.env.CC_DEFAULT_INSTANCE || "your-project";

function token() {
  const t = (process.env.FLEET_TOKEN || "").trim();
  if (t) return t;
  const p = join(homedir(), ".fleet-token");
  if (existsSync(p)) return readFileSync(p, "utf-8").trim();
  return null;
}

async function agent(method, path, body) {
  const tok = token();
  if (!tok) return { _error: "No FCC token (~/.fleet-token or $FLEET_TOKEN) — cannot reach the Alpha control agent." };
  try {
    const res = await fetch(AGENT_URL + path, {
      method,
      headers: { "Content-Type": "application/json", "X-Fleet-Token": tok },
      body: body ? JSON.stringify(body) : undefined,
    });
    const text = await res.text();
    let json;
    try { json = JSON.parse(text); } catch { json = { _raw: text }; }
    if (!res.ok) return { _error: `agent HTTP ${res.status}`, ...json };
    return json;
  } catch (e) {
    return { _error: `cannot reach Command Center agent at ${AGENT_URL}${path}: ${e.message}. ` +
             `Is command_center_server.py running on Alpha? (curl ${AGENT_URL}/cc/health)` };
  }
}

function text(obj) {
  return { content: [{ type: "text", text: typeof obj === "string" ? obj : JSON.stringify(obj, null, 2) }] };
}

const server = new McpServer({ name: "command-center", version: "1.0.0" });

// ── READ: full state ──────────────────────────────────────────────────────────
server.tool(
  "get_state",
  "Get the full reconciled state of a Command Center instance: the AI-authored briefing " +
  "(north star, phase progress, unsolved problems), plus live mechanical state — triggers " +
  "(done/in-flight/blocked), live sessions, spawned workers, spawn candidates, pending spawn " +
  "proposals, and whether the instance is HALTed. Use this first to answer 'what's going on with <project>'.",
  { instance: z.string().optional().describe(`Instance name (default: ${DEFAULT_INSTANCE})`) },
  async ({ instance }) => text(await agent("GET", `/cc/state?instance=${encodeURIComponent(instance || DEFAULT_INSTANCE)}`)),
);

// ── READ: active work summary ─────────────────────────────────────────────────
server.tool(
  "list_active_work",
  "A focused summary of what's actively happening on an instance: blocked triggers (need " +
  "attention first), in-flight triggers, live worker processes, and spawn candidates you could " +
  "launch a worker for. Lighter than get_state — use when you just want the work list.",
  { instance: z.string().optional().describe(`Instance name (default: ${DEFAULT_INSTANCE})`) },
  async ({ instance }) => {
    const d = await agent("GET", `/cc/state?instance=${encodeURIComponent(instance || DEFAULT_INSTANCE)}`);
    if (d._error) return text(d);
    const s = d.state || {};
    return text({
      instance: d.instance, halted: d.halted, spawn_mode: d.spawn_mode,
      blocked: s.triggers_blocked || [],
      in_flight: (s.triggers_in_flight || []).map(t => ({ id: t.id, title: t.title, target: t.target, claimed_by: t.claimed_by })),
      live_workers: (s.workers?.live || []).map(w => ({ id: w.id, task: w.task_title, executor: w.executor, machine: w.machine })),
      live_worker_count: s.workers?.live_count ?? 0,
      spawn_candidates: (s.spawn_candidates || []).map(c => ({ trigger_id: c.trigger_id, title: c.title, spawnable: c.spawnable, gate: c.gate_reason })),
      pending_spawns: (s.pending_spawns || []).filter(p => p.status === "awaiting_confirmation"),
    });
  },
);

// ── READ: remote transcript (Fleet Transcript Agent via fleet_bus.py) ─────────
server.tool(
  "read_transcript",
  "Observe what a fleet session actually DID (not just message it) — search/tail/list a remote " +
  "machine's Claude Code transcripts over the tailnet, prompt-free. Use to verify a worker's real " +
  "actions before trusting a status, or to catch up on what a machine has been doing.",
  {
    machine: z.string().describe("Target machine: beta/alpha/gamma/your-laptop/delta/epsilon/zeta"),
    search: z.string().optional().describe("Search term across the machine's sessions"),
    session: z.string().optional().describe("Scope search to, or tail, one session id"),
    tail: z.number().optional().describe("Return the last N turns of --session"),
    list: z.boolean().optional().describe("List the machine's recent sessions instead of searching"),
  },
  async ({ machine, search, session, tail, list }) => {
    const fb = join(KB_ROOT, "departments", "engineering", "fleet-tools", "fleet_bus.py");
    const args = [fb, "transcript", "--machine", machine];
    if (list) args.push("--list");
    else if (tail != null) { args.push("--tail", String(tail)); if (session) args.push("--session", session); }
    else if (search) { args.push("--search", search); if (session) args.push("--session", session); }
    else return text("read_transcript: provide search, tail (with session), or list");
    return await new Promise(resolve => {
      execFile("python3", args, { timeout: 45000 }, (err, stdout, stderr) =>
        resolve(text(stdout || stderr || (err ? String(err) : "(no output)"))));
    });
  },
);

// ── WRITE: message a worker/session/human over the bus ────────────────────────
server.tool(
  "message_worker",
  "Send a real-time fleet-bus message to a worker, another session, a machine, or the operator " +
  "(--to human = Telegram). Use to nudge/redirect a live worker or relay something to a machine.",
  {
    to: z.string().describe("Target machine (beta/alpha/...) or 'human' for Telegram"),
    body: z.string().describe("Terse message — reference KB paths for anything big"),
    to_session: z.string().optional().describe("Target a specific session id"),
    session: z.string().optional().describe("Your sender id so replies route back (default cc-master)"),
  },
  async ({ to, body, to_session, session }) =>
    text(await agent("POST", "/cc/message", { to, body, to_session, session: session || "cc-master" })),
);

// ── WRITE: spawn a worker (guardrailed; propose-mode by default) ──────────────
server.tool(
  "spawn_worker",
  "Request a guardrailed worker to execute a task. In propose mode (default) this ENQUEUES a " +
  "proposal for the operator to confirm — it does NOT launch. It is refused up front if the guardrails " +
  "fail (build-shaped task with no prior_art, over the concurrency cap, over budget, or the daily " +
  "spawn cap). Tiered executor: 'inference' (Ollama/Gemini/NIM — cheap, no tool loop; " +
  "summarize/classify/extract) or 'claude-worker' (Sonnet, agentic build/debug, commit-local-never-push). " +
  "ALWAYS pass prior_art for a build-shaped task (what you kb-searched / which existing solution you're reusing).",
  {
    instance: z.string().optional().describe(`Instance (default: ${DEFAULT_INSTANCE})`),
    task_title: z.string().describe("Short imperative task title"),
    task_text: z.string().describe("Full task description + done criteria"),
    prior_art: z.string().optional().describe("REQUIRED for build-shaped tasks: what you checked (kb-search + techniques graph) and which existing approach you're reusing"),
    executor: z.enum(["inference", "claude-worker"]).optional().describe("Default claude-worker"),
    runner: z.string().optional().describe("inference runner: ollama/gemini/nim"),
    machine: z.string().optional().describe("Run on this machine (default: the host); repo-owning machine for agentic work"),
    trigger_id: z.string().optional().describe("Existing trigger id this worker executes, if any"),
  },
  async ({ instance, task_title, task_text, prior_art, executor, runner, machine, trigger_id }) =>
    text(await agent("POST", "/cc/spawn", {
      instance: instance || DEFAULT_INSTANCE, task_title, task_text, prior_art,
      executor: executor || "claude-worker", runner, machine, trigger_id,
    })),
);

// ── WRITE: list / confirm / reject pending spawn proposals ────────────────────
server.tool(
  "list_pending_spawns",
  "List spawn proposals awaiting the operator's confirmation for an instance (propose-mode queue).",
  { instance: z.string().optional().describe(`Instance (default: ${DEFAULT_INSTANCE})`) },
  async ({ instance }) => {
    const d = await agent("GET", `/cc/state?instance=${encodeURIComponent(instance || DEFAULT_INSTANCE)}`);
    if (d._error) return text(d);
    return text((d.state?.pending_spawns || []).filter(p => p.status === "awaiting_confirmation"));
  },
);

server.tool(
  "confirm_spawn",
  "Confirm a pending spawn proposal by id — THIS is what actually launches the worker (the " +
  "guardrails are re-checked at launch). Use after the operator says go.",
  {
    instance: z.string().optional().describe(`Instance (default: ${DEFAULT_INSTANCE})`),
    proposal_id: z.string().describe("The proposal id from list_pending_spawns"),
  },
  async ({ instance, proposal_id }) =>
    text(await agent("POST", "/cc/confirm", { instance: instance || DEFAULT_INSTANCE, proposal_id })),
);

server.tool(
  "reject_spawn",
  "Reject/dismiss a pending spawn proposal by id without launching it.",
  {
    instance: z.string().optional().describe(`Instance (default: ${DEFAULT_INSTANCE})`),
    proposal_id: z.string().describe("The proposal id from list_pending_spawns"),
  },
  async ({ instance, proposal_id }) =>
    text(await agent("POST", "/cc/reject", { instance: instance || DEFAULT_INSTANCE, proposal_id })),
);

// ── WRITE: halt / resume (per-instance kill switch) ──────────────────────────
server.tool(
  "halt",
  "HALT an instance: stop new dispatch and SIGTERM every live worker (the kill switch). " +
  "Writes a HALT file the loop honors next cycle. Use resume to lift it.",
  { instance: z.string().optional().describe(`Instance (default: ${DEFAULT_INSTANCE})`) },
  async ({ instance }) => text(await agent("POST", "/cc/halt", { instance: instance || DEFAULT_INSTANCE })),
);

server.tool(
  "resume",
  "Resume a HALTed instance (removes its HALT file so dispatch/spawning continue next cycle).",
  { instance: z.string().optional().describe(`Instance (default: ${DEFAULT_INSTANCE})`) },
  async ({ instance }) => text(await agent("POST", "/cc/resume", { instance: instance || DEFAULT_INSTANCE })),
);

const transport = new StdioServerTransport();
await server.connect(transport);
