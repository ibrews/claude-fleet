#!/usr/bin/env python3
"""Real, guardrailed worker spawning for the Command Center orchestrator (v2).

This closes v1's deliberate carve-out: dispatch.decide_spawn() proved the cap
math but never launched a process. This module actually launches workers —
but ONLY after a launch clears the full guardrail stack, fail-closed:

  1. MODE GATE      — policy spawn.mode == "auto", OR the caller passes
                      confirmed=True (an the operator-approved proposal in propose mode).
                      In propose mode an unconfirmed launch is refused; the
                      caller is expected to enqueue a proposal instead.
  2. PRIOR-ART GATE — a build-shaped task with an empty prior_art summary is
                      refused (reuses prior_art.check_trigger_text — the same
                      gate dispatch.create_trigger() already enforces).
  3. CONCURRENCY    — live worker count < budget.max_concurrent_workers
                      (via guardrail.classify("spawn_worker", ...)).
  4. BUDGET         — cycle-count budget_pct under the stop threshold
                      (guardrail.classify), AND the best-effort real $ ceiling
                      (spawn.budget_usd) when usage-state is readable on the host.
  5. DAILY CAP      — spawns today (from the ledger) < spawn.max_spawns_per_day.
  6. HALT           — enforced by the caller (cycle.py) BEFORE calling launch,
                      and kill_all() terminates live children when HALT appears.

Executors (tiered — fleet-first per the operator's model-routing rules):
  - "inference"     — Ollama / Gemini / NIM single-shot (no Claude budget, no
                      tool loop): summarize/classify/extract/draft/triage.
  - "claude-worker" — agentic build/debug on Sonnet, local subprocess OR
                      `ssh <machine> claude -p` (commit-local-never-push, under
                      settings.worker.json).

State: a durable workers.json in the instance state dir (lives in the
command-center-state repo, so a dead host reinstates from a clone). Every launch
and every reap appends to the same orchestrator-log.jsonl the dashboard reads.

Honest limitations (stated, not faked):
  - For an SSH worker the tracked pid is the LOCAL ssh-client pid, not the remote
    claude pid; killing it closes the channel (usually terminating the remote
    command) but is not a guaranteed remote kill. Robust remote-pid tracking is
    a documented follow-up.
  - The real $ budget (budget_usd) depends on ~/.claude/usage-state.json, which
    is machine-local and absent on some hosts; when absent the always-available
    proxy caps (max_spawns_per_day / max_turns / timeout / max_concurrent) alone
    govern — never silently treated as equivalent to real metering.
"""
import contextlib
import json
import os
import signal
import subprocess
import sys
import time

try:
    import fcntl  # unix only; Alpha (the single-writer host) is a Mac
except ImportError:  # pragma: no cover - non-unix hosts degrade to no-op lock
    fcntl = None

sys.path.insert(0, os.path.dirname(__file__))
import guardrail  # noqa: E402
import ledger as ledger_mod  # noqa: E402
import prior_art  # noqa: E402
import reconcile  # noqa: E402  (reuse pid_alive)

WORKERS_FILENAME = "workers.json"

# Tailnet IPs for the inference tier's Ollama runner. Imported from fleet_bus
# when reachable (single source of truth); a small local fallback keeps spawn.py
# importable in isolation (e.g. unit tests) without the fleet-tools dir on path.
_OLLAMA_FALLBACK_IP = {
    "alpha": "100.64.0.1", "beta": "100.64.0.2", "gamma": "100.64.0.3",
    "delta": "100.64.0.4", "zeta": "100.64.0.5", "epsilon": "100.64.0.6",
    "your-laptop": "100.64.0.7",
}


def _machine_ip(machine, kb_root=None):
    machine = (machine or "").lower()
    try:
        ft = os.path.join(kb_root or os.path.expanduser("~/knowledge"),
                          "departments", "engineering", "fleet-tools")
        if ft not in sys.path:
            sys.path.insert(0, ft)
        import fleet_bus  # noqa: E402
        return fleet_bus.MACHINE_IP.get(machine) or _OLLAMA_FALLBACK_IP.get(machine)
    except Exception:
        return _OLLAMA_FALLBACK_IP.get(machine)


# ---------------------------------------------------------------------------
# workers.json durable state
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _state_lock(state_dir):
    """Serialize read-modify-write of workers.json / pending_spawns.json between
    the two Alpha-local writers — the always-on loop (reap/kill) and the control
    agent (spawn/confirm). Without this, a loop reap and an agent spawn can clobber
    each other's write and lose a worker record. flock is advisory + process-wide;
    both writers go through this helper. Degrades to a no-op where fcntl is absent
    (non-unix), which is fine because the agent + loop only ever run on Alpha."""
    os.makedirs(state_dir, exist_ok=True)
    if fcntl is None:
        yield
        return
    lock_path = os.path.join(state_dir, ".cc.lock")
    f = open(lock_path, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(f, fcntl.LOCK_UN)
        finally:
            f.close()


def load_workers(state_dir):
    path = os.path.join(state_dir, WORKERS_FILENAME)
    if not os.path.exists(path):
        return {"workers": []}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"workers": []}


def save_workers(state_dir, data):
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, WORKERS_FILENAME)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _running(w):
    return w.get("status") == "running" and reconcile.pid_alive(str(w.get("pid")))


def count_live(workers_data):
    """Live = status 'running' AND its pid is actually alive (self-heals a
    workers.json that outlived a crash — a dead pid no longer counts against
    the cap)."""
    return sum(1 for w in workers_data.get("workers", []) if _running(w))


def spawns_today(ledger_path):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    return sum(
        1 for e in ledger_mod.read_all(ledger_path)
        if e.get("event") == "spawn" and e.get("ts_iso", "").startswith(today)
    )


def read_usage_usd(policy):
    """Best-effort real $-spend read. Returns dict or None if unavailable.
    Never raises — a missing/foreign-shaped usage file just means 'unknown',
    and the caller falls back to the proxy caps."""
    cfg = ((policy.get("spawn") or {}).get("budget_usd") or {})
    path = os.path.expanduser(cfg.get("usage_state_path", "~/.claude/usage-state.json"))
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    # usage-state.json shape varies by Claude Code version; probe common keys,
    # never assume. Return what we can find, tagged so the dashboard can show
    # 'unknown' honestly rather than 0.
    for key in ("spent_usd_today", "today_usd", "daily_usd"):
        if isinstance(data.get(key), (int, float)):
            return {"spent_today_usd": float(data[key]), "source": path, "key": key}
    return {"spent_today_usd": None, "source": path, "key": None}


# ---------------------------------------------------------------------------
# The gate — the whole guardrail stack in one fail-closed function
# ---------------------------------------------------------------------------

def gate_spawn(*, task_title, task_text, prior_art_summary, executor,
               workers_data, ledger_path, policy, confirmed=False):
    """Returns (ok: bool, classification: str, reason: str). ok=False => do NOT
    launch. This is the single decision point; launch_worker() calls it and
    refuses on ok=False, so no path can skip a check."""
    spawn_cfg = policy.get("spawn") or {}

    # 1. MODE GATE
    mode = spawn_cfg.get("mode", "propose")
    if mode != "auto" and not confirmed:
        return False, "propose", (
            f"spawn.mode is '{mode}' and this launch is not the operator-confirmed — "
            f"enqueue a proposal (list_pending_spawns/confirm_spawn) instead of launching"
        )

    # 2. PRIOR-ART GATE (build-shaped claude workers only; inference tasks are
    #    not build-shaped by construction, but we still run the check uniformly)
    check = prior_art.check_trigger_text(task_title, task_text, {"prior_art": prior_art_summary})
    if not check["ok"]:
        return False, "refused_no_prior_art", check["reason"]

    # 3 + 4a. CONCURRENCY + cycle-count BUDGET (existing guardrail cap math)
    current = count_live(workers_data)
    budget_pct = ledger_mod.budget_pct_today(ledger_path, policy["budget"]["max_cycles_per_day"])
    cls, reason = guardrail.classify("spawn_worker", policy,
                                     current_workers=current, budget_pct=budget_pct)
    if cls == guardrail.RED:
        return False, cls, reason

    # 5. DAILY SPAWN CAP
    cap = spawn_cfg.get("max_spawns_per_day")
    if isinstance(cap, int):
        today = spawns_today(ledger_path)
        if today >= cap:
            return False, "spawn_beyond_cap", (
                f"max_spawns_per_day reached: {today}/{cap} spawned today"
            )

    # 4b. REAL $ BUDGET (best-effort — only blocks when a real number exists)
    usage = read_usage_usd(policy)
    if usage and usage.get("spent_today_usd") is not None:
        per_day = (spawn_cfg.get("budget_usd") or {}).get("per_day")
        if isinstance(per_day, (int, float)) and usage["spent_today_usd"] >= per_day:
            return False, "exceed_budget", (
                f"real spend ${usage['spent_today_usd']:.2f} >= per_day cap ${per_day:.2f}"
            )

    # cls is GREEN or YELLOW (yellow = spawn allowed but notify same cycle)
    return True, cls, reason


# ---------------------------------------------------------------------------
# Command construction — pure, testable, no side effects
# ---------------------------------------------------------------------------

WORKER_CHARTER = (
    "You are a Command Center WORKER for the \"{instance}\" project, spawned "
    "autonomously by the orchestrator to execute ONE task, then stop. Rules: "
    "(1) Do ONLY the task below; claim it first with "
    "`python3 ~/knowledge/scripts/inbox-claim.sh {trigger}.md` if a trigger id is given. "
    "(2) commit-local-never-push — commit your work to a LOCAL branch only; NEVER push, "
    "merge, deploy, or delete (the master surfaces your branch for human review). "
    "(3) Prior art: {prior_art} — do NOT re-solve what already exists; check the technique graph. "
    "(4) When done OR blocked OR a real decision is needed, report to the master over the "
    "fleet bus: `python3 ~/knowledge/departments/engineering/fleet-tools/fleet_bus.py send "
    "--to alpha --to-session cc-master --session {worker_id} --body \"<terse status + branch name>\"`. "
    "Keep it terse; stop when the done-criteria are met."
)


def build_command(*, executor, runner, machine, engine_dir, prompt, worker_id,
                  instance, trigger_id, prior_art_summary, policy, kb_root=None, model=None):
    """Return (argv:list[str], shell:bool) for the chosen executor/runner.
    Pure — constructs the command, launches nothing. `model` optionally overrides
    the executor's default (a claude tier like 'haiku'/'sonnet', or a specific
    Ollama model like 'llama3.1:8b') — the fleet runs different local LLMs on
    different machines, so the model can't be one hardcoded value."""
    spawn_cfg = policy.get("spawn") or {}

    if executor == "inference":
        runner = runner or spawn_cfg["executors"]["inference"].get("default_runner", "ollama")
        if runner == "ollama":
            ip = _machine_ip(machine or "alpha", kb_root)
            ollama_model = model or spawn_cfg["executors"]["inference"].get("default_ollama_model", "gemma3:27b")
            body = json.dumps({"model": ollama_model, "prompt": prompt, "stream": False})
            # curl to the fleet Ollama endpoint (fleet/dispatch.md pattern).
            return (["curl", "-s", f"http://{ip}:11434/api/generate", "-d", body], False)
        if runner == "gemini":
            # gemini CLI, non-interactive (fleet/dispatch.md). Needs $GEMINI_API_KEY in env.
            return (["gemini", "-p", prompt, "-y"], False)
        if runner == "nim":
            body = json.dumps({
                "model": "meta/llama-3.3-70b-instruct",
                "messages": [{"role": "user", "content": prompt}],
            })
            return (["curl", "-s", "https://integrate.api.nvidia.com/v1/chat/completions",
                     "-H", "Content-Type: application/json",
                     "-H", "Authorization: Bearer $NVIDIA_API_KEY", "-d", body], True)
        raise ValueError(f"unknown inference runner '{runner}'")

    if executor == "claude-worker":
        cw = spawn_cfg["executors"]["claude-worker"]
        model = model or cw.get("model", "sonnet")
        max_turns = str(spawn_cfg.get("max_turns_per_worker", 30))
        perm = cw.get("permission_mode", "acceptEdits")
        settings_path = os.path.join(engine_dir, cw.get("settings_file", "settings.worker.json"))
        charter = WORKER_CHARTER.format(
            instance=instance, trigger=trigger_id or "<none>", worker_id=worker_id,
            prior_art=prior_art_summary or "n/a",
        )
        claude_args = [
            "claude", "-p", prompt,
            "--model", model, "--max-turns", max_turns,
            "--permission-mode", perm, "--settings", settings_path,
            "--output-format", "json", "--append-system-prompt", charter,
        ]
        if machine and machine.lower() != _local_machine(kb_root):
            # Remote: hop via ssh. The remote settings path mirrors the KB layout
            # (git-synced), so engine_dir resolves the same on the target. Quote
            # the whole remote command as one string for ssh.
            remote = " ".join(_shq(a) for a in claude_args)
            return (["ssh", machine.lower(), remote], False)
        return (claude_args, False)

    raise ValueError(f"unknown executor '{executor}'")


def _local_machine(kb_root=None):
    try:
        ft = os.path.join(kb_root or os.path.expanduser("~/knowledge"),
                          "departments", "engineering", "fleet-tools")
        if ft not in sys.path:
            sys.path.insert(0, ft)
        import fleet_bus  # noqa: E402
        return fleet_bus.my_machine()
    except Exception:
        import socket
        return socket.gethostname().lower().split(".")[0]


def _shq(s):
    """Minimal single-quote shell escape for embedding argv into an ssh string."""
    return "'" + str(s).replace("'", "'\\''") + "'"


# ---------------------------------------------------------------------------
# Launch / reap / kill
# ---------------------------------------------------------------------------

def launch_worker(*, task_title, task_text, prior_art_summary, executor, runner=None,
                  machine=None, trigger_id=None, instance, engine_dir, state_dir,
                  ledger_path, policy, confirmed=False, kb_root=None,
                  dry_run=False, command_override=None, model=None):
    """Gate, then actually launch (unless dry_run). Returns a dict:
    {ok, classification, reason, worker (record|None)}. On ok=False nothing is
    launched. command_override (a ready argv) is for tests — it still passes the
    full gate, but launches the harmless override instead of a real executor."""
    workers_data = load_workers(state_dir)
    ok, cls, reason = gate_spawn(
        task_title=task_title, task_text=task_text, prior_art_summary=prior_art_summary,
        executor=executor, workers_data=workers_data, ledger_path=ledger_path,
        policy=policy, confirmed=confirmed,
    )
    if not ok:
        ledger_mod.append(ledger_path, {
            "event": "spawn_refused", "classification": cls, "reason": reason,
            "executor": executor, "task_title": task_title, "instance": instance,
        })
        return {"ok": False, "classification": cls, "reason": reason, "worker": None}

    worker_id = f"cc-worker-{instance}-{int(time.time())}-{len(workers_data['workers'])}"
    prompt = f"{task_title}\n\n{task_text}".strip()
    if command_override is not None:
        argv, shell = list(command_override), False
    else:
        argv, shell = build_command(
            executor=executor, runner=runner, machine=machine, engine_dir=engine_dir,
            prompt=prompt, worker_id=worker_id, instance=instance, trigger_id=trigger_id,
            prior_art_summary=prior_art_summary, policy=policy, kb_root=kb_root, model=model,
        )

    record = {
        "id": worker_id, "instance": instance, "trigger_id": trigger_id,
        "executor": executor, "runner": runner, "machine": machine or _local_machine(kb_root),
        "task_title": task_title, "classification": cls,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "started_epoch": int(time.time()), "pid": None, "status": "pending",
        "exit_code": None, "log": None,
        "command_preview": (" ".join(argv) if not shell else argv[0])[:300],
    }

    if dry_run:
        record["status"] = "dry_run"
        ledger_mod.append(ledger_path, {
            "event": "spawn", "dry_run": True, "worker_id": worker_id,
            "executor": executor, "runner": runner, "machine": record["machine"],
            "classification": cls, "task_title": task_title, "instance": instance,
        })
        return {"ok": True, "classification": cls, "reason": "DRY RUN — not launched", "worker": record}

    logs_dir = os.path.join(state_dir, "worker-logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_path = os.path.join(logs_dir, f"{worker_id}.log")
    record["log"] = log_path
    logf = open(log_path, "w")
    try:
        if shell:
            proc = subprocess.Popen(" ".join(argv), shell=True, stdout=logf,
                                    stderr=subprocess.STDOUT, start_new_session=True)
        else:
            proc = subprocess.Popen(argv, stdout=logf, stderr=subprocess.STDOUT,
                                    start_new_session=True)
    except Exception as e:
        logf.close()
        record["status"] = "failed_to_launch"
        ledger_mod.append(ledger_path, {
            "event": "spawn_refused", "classification": "launch_error",
            "reason": str(e), "executor": executor, "task_title": task_title,
            "instance": instance,
        })
        return {"ok": False, "classification": "launch_error", "reason": str(e), "worker": record}

    record["pid"] = proc.pid
    record["status"] = "running"
    # Re-load under the lock before appending: the gate's workers_data may be
    # slightly stale (a concurrent reap could have run), and we must never lose
    # this append. The cap was already checked above; a rare off-by-one under
    # heavy concurrent spawning is acceptable (and auto-spawn is off by default).
    with _state_lock(state_dir):
        fresh = load_workers(state_dir)
        fresh["workers"].append(record)
        save_workers(state_dir, fresh)
    ledger_mod.append(ledger_path, {
        "event": "spawn", "worker_id": worker_id, "pid": proc.pid,
        "executor": executor, "runner": runner, "machine": record["machine"],
        "classification": cls, "task_title": task_title, "instance": instance,
        "confirmed": confirmed,
    })
    return {"ok": True, "classification": cls, "reason": reason, "worker": record}


def _probe(pid):
    """Return (exited: bool, exit_code|None). Works whether or not the worker is
    a child of THIS process: for our own child we non-blocking-waitpid it (which
    also reaps the zombie, so a same-process launch+reap — the self-test, and any
    single long-lived reaper — reports exit correctly); for a reparented worker
    (the production case, where the launching cycle process has already exited and
    launchd owns the child) waitpid raises ChildProcessError and we fall back to
    os.kill(pid, 0) liveness."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True, None
    try:
        wpid, status = os.waitpid(pid, os.WNOHANG)
        if wpid == 0:
            return False, None
        code = os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else None
        return True, code
    except ChildProcessError:
        return (not reconcile.pid_alive(str(pid))), None
    except OSError:
        return True, None


def reap(state_dir, ledger_path, policy):
    """Finalize exited workers and SIGTERM any that overran their timeout.
    Returns a list of state-change dicts. Call once per cycle. Locked so a
    concurrent agent spawn-append is never clobbered."""
    timeout = (policy.get("spawn") or {}).get("timeout_seconds_per_worker", 3600)
    changes = []
    now = int(time.time())
    with _state_lock(state_dir):
        workers_data = load_workers(state_dir)
        for w in workers_data.get("workers", []):
            if w.get("status") != "running":
                continue
            pid = w.get("pid")
            exited, code = _probe(pid)
            if not exited and (now - w.get("started_epoch", now)) > timeout:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except (ProcessLookupError, ValueError, PermissionError):
                    pass
                w["status"] = "timeout"
                w["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                changes.append({"worker_id": w["id"], "status": "timeout"})
                ledger_mod.append(ledger_path, {"event": "worker_end", "worker_id": w["id"],
                                                "status": "timeout"})
            elif exited:
                w["status"] = "done" if (code in (0, None)) else "failed"
                w["exit_code"] = code
                w["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                changes.append({"worker_id": w["id"], "status": w["status"], "exit_code": code})
                ledger_mod.append(ledger_path, {"event": "worker_end", "worker_id": w["id"],
                                                "status": w["status"], "exit_code": code})
        if changes:
            save_workers(state_dir, workers_data)
    return changes


def kill_all(state_dir, ledger_path, *, reason="HALT"):
    """SIGTERM every live worker — the HALT kill switch's 'terminates spawned
    children' clause. Returns the list of killed worker ids."""
    killed = []
    with _state_lock(state_dir):
        workers_data = load_workers(state_dir)
        for w in workers_data.get("workers", []):
            if _running(w):
                try:
                    os.kill(int(w["pid"]), signal.SIGTERM)
                except (ProcessLookupError, ValueError, PermissionError):
                    pass
                w["status"] = "killed"
                w["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                killed.append(w["id"])
                ledger_mod.append(ledger_path, {"event": "worker_killed", "worker_id": w["id"],
                                                "reason": reason})
        if killed:
            save_workers(state_dir, workers_data)
    return killed


def summarize(state_dir):
    """Compact live/recent view for the dashboard + MCP get_state."""
    workers_data = load_workers(state_dir)
    ws = workers_data.get("workers", [])
    return {
        "live": [w for w in ws if _running(w)],
        "recent": ws[-10:],
        "live_count": count_live(workers_data),
    }


def identify_candidates(state, kb_root):
    """Read-only: unclaimed, pending triggers for this instance, each annotated
    with the prior-art gate result. Does NOT launch or propose — it only SURFACES
    what a human (via the Desktop MCP) or a future auto-mode could spawn a worker
    for. Keeping this side-effect-free is deliberate: autonomous candidate
    *proposal* is noise/risk that belongs behind the same propose->auto graduation
    as launching, not in the always-on reconcile pass."""
    import re as _re
    cands = []
    for t in state.get("triggers_in_flight", []):
        if (t.get("claimed_by") or "").strip():
            continue
        if t.get("status", "pending") not in ("pending", ""):
            continue
        path = os.path.join(kb_root, t.get("file", ""))
        fields, body = reconcile.parse_frontmatter(path) if os.path.exists(path) else ({}, "")
        m = _re.search(r"## Task\s*\n+(.*?)(?:\n##|\Z)", body, _re.DOTALL)
        task_text = m.group(1).strip() if m else body
        chk = prior_art.check_trigger_text(t.get("title", ""), task_text, fields)
        cands.append({
            "trigger_id": t.get("id"), "title": t.get("title", ""), "file": t.get("file"),
            "target": t.get("target", ""),
            "build_shaped": chk["build_shaped"], "spawnable": chk["ok"],
            "prior_art": (fields.get("prior_art") or "").strip(),
            "gate_reason": chk["reason"],
        })
    return cands


# ---------------------------------------------------------------------------
# pending_spawns.json — the propose-then-confirm queue (Desktop MCP + cc-master)
# ---------------------------------------------------------------------------

PENDING_FILENAME = "pending_spawns.json"


def load_pending(state_dir):
    path = os.path.join(state_dir, PENDING_FILENAME)
    if not os.path.exists(path):
        return {"pending": []}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"pending": []}


def save_pending(state_dir, data):
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, PENDING_FILENAME), "w") as f:
        json.dump(data, f, indent=2)


def enqueue_proposal(state_dir, proposal):
    """Add a spawn proposal awaiting the operator's 'go'. proposal carries everything
    launch_worker needs (task_title/text, executor, machine, trigger_id,
    prior_art_summary). Returns the assigned proposal id."""
    with _state_lock(state_dir):
        data = load_pending(state_dir)
        pid = f"prop-{int(time.time())}-{len(data['pending'])}"
        proposal = dict(proposal, id=pid,
                        proposed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        status="awaiting_confirmation")
        data["pending"].append(proposal)
        save_pending(state_dir, data)
    return pid


def resolve_proposal(state_dir, proposal_id, status):
    """Mark a proposal confirmed/rejected. Returns the proposal dict or None."""
    with _state_lock(state_dir):
        data = load_pending(state_dir)
        for p in data["pending"]:
            if p["id"] == proposal_id:
                p["status"] = status
                p["resolved_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                save_pending(state_dir, data)
                return p
    return None


if __name__ == "__main__":
    # Self-test: exercises gate -> launch -> reap -> kill with a HARMLESS
    # command_override (never touches Claude/network). Also proves the gate
    # refuses in propose mode and on a build-shaped task with no prior art.
    import tempfile

    engine_dir = os.path.join(os.path.dirname(__file__), "..")
    policy = guardrail.load_policy(os.path.join(engine_dir, "policy.json"))

    with tempfile.TemporaryDirectory() as tmp:
        state_dir = os.path.join(tmp, "state")
        ledger_path = os.path.join(state_dir, "orchestrator-log.jsonl")

        # (a) propose mode, unconfirmed -> refused
        r = launch_worker(task_title="Summarize the roadmap", task_text="Give a 3-line summary.",
                          prior_art_summary="", executor="inference", instance="selftest",
                          engine_dir=engine_dir, state_dir=state_dir, ledger_path=ledger_path,
                          policy=policy, command_override=["true"])
        print("propose/unconfirmed:", r["classification"], "-", r["reason"][:70])
        assert not r["ok"] and r["classification"] == "propose"

        # (b) confirmed build-shaped w/ NO prior art -> refused
        r = launch_worker(task_title="Build a new groom pipeline from scratch",
                          task_text="Implement it.", prior_art_summary="",
                          executor="claude-worker", instance="selftest", engine_dir=engine_dir,
                          state_dir=state_dir, ledger_path=ledger_path, policy=policy,
                          confirmed=True, command_override=["true"])
        print("confirmed/build/no-prior-art:", r["classification"], "-", r["reason"][:60])
        assert not r["ok"] and r["classification"] == "refused_no_prior_art"

        # (c) confirmed, not build-shaped -> LAUNCHES a harmless override
        r = launch_worker(task_title="Summarize the roadmap", task_text="3-line summary.",
                          prior_art_summary="", executor="inference", instance="selftest",
                          engine_dir=engine_dir, state_dir=state_dir, ledger_path=ledger_path,
                          policy=policy, confirmed=True, command_override=["sleep", "0.3"])
        print("confirmed/ok:", r["ok"], r["classification"], "pid", r["worker"]["pid"])
        assert r["ok"] and r["worker"]["pid"]
        assert count_live(load_workers(state_dir)) == 1

        time.sleep(0.6)
        changes = reap(state_dir, ledger_path, policy)
        print("reap after exit:", changes)
        assert changes and changes[0]["status"] == "done"
        assert count_live(load_workers(state_dir)) == 0

        # (d) kill_all on a live long worker
        r = launch_worker(task_title="Draft notes", task_text="ok", prior_art_summary="",
                          executor="inference", instance="selftest", engine_dir=engine_dir,
                          state_dir=state_dir, ledger_path=ledger_path, policy=policy,
                          confirmed=True, command_override=["sleep", "30"])
        assert r["ok"]
        killed = kill_all(state_dir, ledger_path)
        print("kill_all:", killed)
        assert killed and count_live(load_workers(state_dir)) == 0

        # (e) command builders are pure + shaped right
        argv, shell = build_command(executor="claude-worker", runner=None, machine=None,
                                    engine_dir=engine_dir, prompt="do X", worker_id="w1",
                                    instance="selftest", trigger_id="t1", prior_art_summary="p",
                                    policy=policy)
        assert argv[0] == "claude" and "--settings" in argv and "--max-turns" in argv
        argv2, _ = build_command(executor="inference", runner="ollama", machine="beta",
                                 engine_dir=engine_dir, prompt="sum", worker_id="w2",
                                 instance="selftest", trigger_id=None, prior_art_summary="",
                                 policy=policy)
        assert argv2[0] == "curl" and "11434" in argv2[2]
        print("build_command shapes: claude-worker + inference OK")
        print("\nspawn.py self-test PASSED")
