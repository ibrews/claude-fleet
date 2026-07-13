#!/usr/bin/env python3
"""Command Center control agent — the single-writer, host-side HTTP service.

WHY THIS EXISTS (single-writer + co-located-reap): spawned workers must be
launched AND reaped on ONE host, because reap() uses local pid liveness — a
worker launched on Alpha has a Alpha pid that only Alpha can check. The always-on loop
(run-loop.sh) already lives on Alpha and owns command-center-state. So every state
WRITE (spawn / confirm / halt) must also happen on Alpha, co-located with the loop
and its reap. This agent is that Alpha-side writer. The Desktop MCP (which runs on
the operator's Mac, wherever Claude Desktop is) is a THIN PROXY that calls this agent over
the tailnet — it never launches or reaps locally.

Same posture as the Fleet Transcript Agent (fleet_transcript_server.py, :3737) and
the bus/Ollama: a small stdlib HTTP service bound to the tailnet, gated by the
shared ~/.fleet-token. Pure stdlib, deploys via the git-synced KB, no npm/pip step.

Deterministic by design (per build-tools-that-run-without-ai): this agent runs the
guardrail + spawn mechanics without any Claude session. The REASONING surface is
Claude Desktop (via the MCP) and the cc-master bus session — they decide WHAT to
spawn; this agent enforces the guardrails and does the mechanical launch.

Run on Alpha (as a LaunchAgent):
    python3 command_center_server.py serve                 # binds 0.0.0.0:3838
    python3 command_center_server.py serve --port 3838 --bind 100.64.0.1

Endpoints (JSON; all except /cc/health require X-Fleet-Token):
    GET  /cc/health                       liveness (no auth)
    GET  /cc/instances                    list every project running a command center
    GET  /cc/state?instance=<name>        full reconciled state + workers + candidates + pending
    POST /cc/spawn                        {instance, task_title, task_text, prior_art, executor,
                                           runner?, machine?, trigger_id?, confirmed?} ->
                                           propose-mode: enqueues a proposal; auto/confirmed: launches
    POST /cc/confirm                      {instance, proposal_id} -> launch a confirmed proposal
    POST /cc/reject                       {instance, proposal_id}
    POST /cc/halt                         {instance} -> write HALT + SIGTERM live workers
    POST /cc/resume                       {instance} -> remove HALT
    POST /cc/message                      {to, body, to_session?, session?} -> fleet_bus.py send

SAFETY: this agent can spawn workers and toggle HALT, but it is bound to the tailnet
and token-gated, and every spawn still passes the full guardrail stack in spawn.py
(mode/prior-art/cap/budget/daily). It NEVER flips policy.spawn.mode — going from
propose to auto is a manual policy.json edit the operator makes, not an endpoint.
"""
import argparse
import glob
import json
import os
import socket
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ENGINE_DIR, "lib"))
import dashboard  # noqa: E402
import guardrail  # noqa: E402
import reconcile  # noqa: E402
import spawn  # noqa: E402

# cycle.py owns resolve_paths + discover_instances; reuse them (importing cycle
# does not run its argparse main — that is __main__-guarded).
sys.path.insert(0, ENGINE_DIR)
import cycle  # noqa: E402

DEFAULT_PORT = int(os.environ.get("CC_AGENT_PORT", "3838"))
KB_ROOT = os.path.expanduser(os.environ.get("KB_ROOT", "~/knowledge"))


def expected_token():
    t = os.environ.get("FLEET_TOKEN", "").strip()
    if t:
        return t
    p = Path.home() / ".fleet-token"
    return p.read_text().strip() if p.exists() else None


def load_policy():
    return guardrail.load_policy(os.path.join(ENGINE_DIR, "policy.json"))


def find_instance(name):
    """Resolve an instance name -> (config, paths). Raises KeyError if unknown."""
    path = os.path.join(KB_ROOT, "projects", name, "command-center", "instance.json")
    if not os.path.exists(path):
        # fall back to a scan (name may differ from the folder)
        for p in glob.glob(os.path.join(KB_ROOT, "projects", "*", "command-center", "instance.json")):
            try:
                cfg = json.load(open(p))
            except (json.JSONDecodeError, OSError):
                continue
            if cfg.get("name") == name:
                return cfg, cycle.resolve_paths(cfg, KB_ROOT)
        raise KeyError(name)
    cfg = json.load(open(path))
    return cfg, cycle.resolve_paths(cfg, KB_ROOT)


# ── operations ────────────────────────────────────────────────────────────────

def op_state(name):
    cfg, paths = find_instance(name)
    state = reconcile.build_state(KB_ROOT, cfg)
    import time
    state["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state["workers"] = spawn.summarize(paths["instance_state_dir"])
    state["spawn_candidates"] = spawn.identify_candidates(state, KB_ROOT)
    state["pending_spawns"] = spawn.load_pending(paths["instance_state_dir"]).get("pending", [])
    briefing = dashboard.load_briefing(paths["briefing"])
    halted = any(os.path.exists(p) for p in paths["halt_candidates"])
    return {
        "instance": name, "halted": halted,
        "spawn_mode": (load_policy().get("spawn") or {}).get("mode", "propose"),
        "briefing": briefing, "state": state,
    }


def op_instances():
    return {"instances": cycle.discover_instances(KB_ROOT)}


def op_spawn(body):
    name = body["instance"]
    cfg, paths = find_instance(name)
    policy = load_policy()
    mode = (policy.get("spawn") or {}).get("mode", "propose")
    state_dir, ledger = paths["instance_state_dir"], paths["ledger"]
    confirmed = bool(body.get("confirmed"))

    common = dict(
        task_title=body.get("task_title", ""), task_text=body.get("task_text", ""),
        prior_art_summary=body.get("prior_art", ""), executor=body.get("executor", "claude-worker"),
        runner=body.get("runner"), machine=body.get("machine"), trigger_id=body.get("trigger_id"),
        model=body.get("model"),
        instance=name, engine_dir=ENGINE_DIR, state_dir=state_dir, ledger_path=ledger,
        policy=policy, kb_root=KB_ROOT,
    )

    # Preview the REAL gate (bypass only the mode check) so a proposal that would
    # be refused (no prior art / over cap / over budget) is rejected up front
    # instead of enqueued to fail later.
    ok, cls, reason = spawn.gate_spawn(
        task_title=common["task_title"], task_text=common["task_text"],
        prior_art_summary=common["prior_art_summary"], executor=common["executor"],
        workers_data=spawn.load_workers(state_dir), ledger_path=ledger, policy=policy,
        confirmed=True,
    )
    if not ok:
        return {"status": "refused", "classification": cls, "reason": reason}

    if mode == "auto" or confirmed:
        result = spawn.launch_worker(**common, confirmed=True)
        return {"status": "launched" if result["ok"] else "refused", **result}

    # propose mode: enqueue for the operator's confirmation
    prop_id = spawn.enqueue_proposal(state_dir, {
        "task_title": common["task_title"], "task_text": common["task_text"],
        "prior_art": common["prior_art_summary"], "executor": common["executor"],
        "runner": common["runner"], "machine": common["machine"], "model": common["model"],
        "trigger_id": common["trigger_id"], "preview_classification": cls,
    })
    return {"status": "proposed", "proposal_id": prop_id, "classification": cls,
            "note": "propose mode — awaiting the operator's confirm_spawn/POST /cc/confirm"}


def op_confirm(body):
    name, prop_id = body["instance"], body["proposal_id"]
    cfg, paths = find_instance(name)
    policy = load_policy()
    state_dir, ledger = paths["instance_state_dir"], paths["ledger"]
    prop = spawn.resolve_proposal(state_dir, prop_id, "confirmed")
    if not prop:
        return {"status": "not_found", "proposal_id": prop_id}
    result = spawn.launch_worker(
        task_title=prop.get("task_title", ""), task_text=prop.get("task_text", ""),
        prior_art_summary=prop.get("prior_art", ""), executor=prop.get("executor", "claude-worker"),
        runner=prop.get("runner"), machine=prop.get("machine"), trigger_id=prop.get("trigger_id"),
        model=prop.get("model"),
        instance=name, engine_dir=ENGINE_DIR, state_dir=state_dir, ledger_path=ledger,
        policy=policy, confirmed=True, kb_root=KB_ROOT,
    )
    return {"status": "launched" if result["ok"] else "refused", "proposal_id": prop_id, **result}


def op_reject(body):
    name, prop_id = body["instance"], body["proposal_id"]
    cfg, paths = find_instance(name)
    prop = spawn.resolve_proposal(paths["instance_state_dir"], prop_id, "rejected")
    return {"status": "rejected" if prop else "not_found", "proposal_id": prop_id}


def op_halt(body, resume=False):
    name = body["instance"]
    cfg, paths = find_instance(name)
    halt_path = paths["halt_candidates"][0]  # the per-instance HALT (state repo)
    import ledger as ledger_mod
    if resume:
        removed = os.path.exists(halt_path)
        if removed:
            os.remove(halt_path)
        return {"status": "resumed" if removed else "not_halted", "halt_path": halt_path}
    os.makedirs(os.path.dirname(halt_path), exist_ok=True)
    with open(halt_path, "w") as f:
        f.write("HALT written by command_center_server /cc/halt\n")
    killed = spawn.kill_all(paths["instance_state_dir"], paths["ledger"], reason="HALT:/cc/halt")
    return {"status": "halted", "halt_path": halt_path, "workers_killed": killed}


def op_message(body):
    fleet_bus = os.path.join(KB_ROOT, "departments", "engineering", "fleet-tools", "fleet_bus.py")
    cmd = ["python3", fleet_bus, "send", "--to", body["to"], "--body", body["body"]]
    if body.get("to_session"):
        cmd += ["--to-session", body["to_session"]]
    if body.get("session"):
        cmd += ["--session", body["session"]]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return {"status": "sent" if r.returncode == 0 else "error",
                "output": (r.stdout or r.stderr).strip()}
    except Exception as e:
        return {"status": "error", "output": str(e)}


# ── HTTP layer (mirrors fleet_transcript_server.py) ─────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "command-center-agent/1.0"

    def log_message(self, *a):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _authed(self):
        want = expected_token()
        if not want:
            self._send(500, {"error": "agent has no token (~/.fleet-token or $FLEET_TOKEN)"})
            return False
        if (self.headers.get("X-Fleet-Token") or "").strip() != want:
            self._send(401, {"error": "missing or bad X-Fleet-Token"})
            return False
        return True

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode() or "{}")

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/cc/health":
            self._send(200, {"ok": True, "service": "command-center-agent", "version": "1.0"})
            return
        if not self._authed():
            return
        try:
            if u.path == "/cc/instances":
                self._send(200, op_instances())
            elif u.path == "/cc/state":
                self._send(200, op_state(q["instance"]))
            else:
                self._send(404, {"error": "unknown path"})
        except KeyError as e:
            self._send(400, {"error": f"unknown/missing instance {e}"})
        except Exception as e:
            self._send(500, {"error": str(e)})

    def do_POST(self):
        u = urlparse(self.path)
        if not self._authed():
            return
        try:
            body = self._body()
            routes = {
                "/cc/spawn": lambda: op_spawn(body),
                "/cc/confirm": lambda: op_confirm(body),
                "/cc/reject": lambda: op_reject(body),
                "/cc/halt": lambda: op_halt(body),
                "/cc/resume": lambda: op_halt(body, resume=True),
                "/cc/message": lambda: op_message(body),
            }
            if u.path in routes:
                self._send(200, routes[u.path]())
            else:
                self._send(404, {"error": "unknown path"})
        except KeyError as e:
            self._send(400, {"error": f"missing field {e}"})
        except Exception as e:
            self._send(500, {"error": str(e)})


def serve(port, bind):
    if not expected_token():
        print("WARNING: no ~/.fleet-token or $FLEET_TOKEN — every authed request will 500", file=sys.stderr)
    httpd = ThreadingHTTPServer((bind, port), Handler)
    print(f"[command-center-agent] serving on {bind}:{port} (kb_root={KB_ROOT})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=DEFAULT_PORT)
    sv.add_argument("--bind", default="0.0.0.0")
    args = ap.parse_args()
    if args.cmd == "serve":
        serve(args.port, args.bind)
