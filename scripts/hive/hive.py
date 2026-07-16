#!/usr/bin/env python3
"""
Fleet Hive orchestrator CLI.

A thin, stdlib-only Python client for a LiteLLM gateway (see gateway-config.example.yaml)
that adds parallel fan-out, cross-family adversarial judging, and dispatch to a live
Claude Code session over the fleet's session bus (scripts/fleet-bus-server.js).

The gateway does the hard part (routing, fallbacks, load-balancing, cooldowns) — this
CLI is what a human or another agent actually calls. See docs/18-fleet-hive.md.
"""

import argparse
import concurrent.futures
from collections import deque
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# Constants & helpers
# --------------------------------------------------------------------------- #

# Deliberately NOT 4100 — that's the documented default port for this repo's own
# session bus (scripts/fleet-bus-server.js, docs/16-session-bus.md). Point this at
# your gateway machine's Tailscale hostname, e.g. http://beta:4101.
GATEWAY = os.environ.get("HIVE_GATEWAY", "http://localhost:4101")
HIVE_KEY = os.environ.get("HIVE_KEY", "")  # must match general_settings.master_key
RUN_LOG = Path(os.environ.get("HIVE_RUN_LOG", str(Path.home() / ".hive" / "runs.jsonl")))

# Model "family" is used only to keep a judge from grading its own generator's output.
# The mapping below is illustrative — replace it with whatever model families you
# actually route to in gateway-config.yaml. Substring match against the LiteLLM model
# string LiteLLM reports (or your alias, if you keep the ALIAS_FAMILY table in sync).
FAMILY: Dict[str, str] = {
    "qwen": "qwen",
    "deepseek": "deepseek",
    "gemini": "gemini",
    "gpt-oss": "gpt-oss",
    "llama": "llama",
    "glm": "glm",
    "gemma": "gemma",
    "mixtral": "mixtral",
}

# hive-* aliases carry no family substring in their name, so map them explicitly.
# Must stay in sync with gateway-config.yaml's model_group_alias section.
ALIAS_FAMILY: Dict[str, str] = {
    "hive-fast": "llama",
    "hive-coder": "qwen",
    "hive-drafter": "llama",
    "hive-reasoner": "qwen",
    "hive-judge-a": "qwen",
    "hive-judge-b": "gpt-oss",
    "hive-judge-c": "gemini",
}


def family_of(name: str) -> Optional[str]:
    """Return the model family for *name*: alias table first, then substring match."""
    key = name.lower()
    if key in ALIAS_FAMILY:
        return ALIAS_FAMILY[key]
    for sub, fam in FAMILY.items():
        if sub in key:
            return fam
    return None


# Example deny-list: backends you've found (via your own eval program, or public
# reports) to be unreliable narrators on citation/research tasks — refuse them for
# that task_type regardless of how well they otherwise score. Empty by default;
# populate from your own findings. See docs/18-fleet-hive.md for the pattern this
# came from (a personal model bake-off that caught specific models fabricating
# citations while sounding confident).
DENY_CITATION: set = set()

# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class HiveError(Exception):
    """Base class for hive errors."""


class HiveDenyError(HiveError):
    """Raised when a request violates the citation/research deny-list."""


class HiveConfigError(HiveError):
    """Raised for configuration problems (e.g., insufficient judges)."""


# --------------------------------------------------------------------------- #
# Core network helpers
# --------------------------------------------------------------------------- #


def _urlopen(url: str, data: Optional[bytes] = None, method: str = "GET", timeout: int = 300) -> Any:
    """Open *url* with the required headers.

    Client timeout must exceed the gateway's own request_timeout so LiteLLM has
    room to retry and fail over to a fallback deployment before we give up.
    """
    headers = {
        "User-Agent": "curl/8.6.0",  # some providers (observed: Cerebras) 403 bare
                                      # python-urllib User-Agent strings — see
                                      # docs/18-fleet-hive.md § Gotchas.
        "Content-Type": "application/json",
    }
    if HIVE_KEY:
        headers["Authorization"] = f"Bearer {HIVE_KEY}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    return urllib.request.urlopen(req, timeout=timeout)


# --------------------------------------------------------------------------- #
# Core API functions
# --------------------------------------------------------------------------- #


def gateway_chat(
    alias: str,
    prompt: str,
    max_tokens: int = 4096,
    task_type: str = "general",
    timeout: int = 300,
) -> Dict[str, Any]:
    """
    Send a chat completion request to the LiteLLM gateway.

    Returns a dict with keys: alias, text, latency_ms, ok, error, tokens_in, tokens_out
    """
    if task_type in {"citation", "research"} and any(deny in alias for deny in DENY_CITATION):
        raise HiveDenyError(f"Denied backend for citation/research task: {alias}")

    payload = {
        "model": alias,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    data = json.dumps(payload).encode("utf-8")
    start = time.time()

    def _do_request():
        # Runs in a worker thread so the TOTAL deadline below always holds. A plain
        # socket timeout only bounds individual blocking reads — a gateway that
        # dribbles keepalive bytes while retrying upstream deployments can hold a
        # naive client open far longer than any single read timeout would suggest.
        try:
            with _urlopen(f"{GATEWAY}/v1/chat/completions", data=data, method="POST", timeout=timeout) as resp:
                return resp.read().decode(), resp.getcode()
        except urllib.error.HTTPError as e:
            return e.read().decode(), e.code

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            raw, status = pool.submit(_do_request).result(timeout=timeout)
    except Exception as e:
        latency = int((time.time() - start) * 1000)
        err = f"total deadline ({timeout}s) exceeded" if isinstance(e, concurrent.futures.TimeoutError) else str(e)
        return {"alias": alias, "text": "", "latency_ms": latency, "ok": False,
                "error": err, "tokens_in": 0, "tokens_out": 0}

    latency = int((time.time() - start) * 1000)
    if status != 200:
        return {"alias": alias, "text": "", "latency_ms": latency, "ok": False,
                "error": f"HTTP {status}: {raw}", "tokens_in": 0, "tokens_out": 0}

    try:
        resp_json = json.loads(raw)
        choice = resp_json.get("choices", [{}])[0]
        text = choice.get("message", {}).get("content", "")
        usage = resp_json.get("usage", {})
        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)
    except Exception as e:
        return {"alias": alias, "text": "", "latency_ms": latency, "ok": False,
                "error": f"Parse error: {e}", "tokens_in": 0, "tokens_out": 0}

    return {"alias": alias, "text": text, "latency_ms": latency, "ok": True,
            "error": None, "tokens_in": tokens_in, "tokens_out": tokens_out}


def swarm(aliases: List[str], prompt: str, **kw) -> List[Dict[str, Any]]:
    """Fan out chat requests to *aliases* concurrently; results in input order."""
    results: List[Optional[Dict[str, Any]]] = [None] * len(aliases)

    def _worker(idx: int, alias: str):
        results[idx] = gateway_chat(alias, prompt, **kw)

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(aliases)) as executor:
        futures = [executor.submit(_worker, i, alias) for i, alias in enumerate(aliases)]
        concurrent.futures.wait(futures)

    return results  # type: ignore[return-value]  # all slots filled


def check(
    gen_alias: str,
    task: str,
    judges: List[str] = ["hive-judge-a", "hive-judge-b", "hive-judge-c"],
    **kw,
) -> Dict[str, Any]:
    """
    Generate with *gen_alias*, then have judges from OTHER model families evaluate it.

    Returns a dict with keys: generation, verdicts (list), pass (bool — majority PASS).
    """
    generation = gateway_chat(gen_alias, task, **kw)

    if not generation.get("ok") or not generation.get("text", "").strip():
        return {"generation": generation, "verdicts": [], "pass": False}

    gen_family = family_of(gen_alias)
    usable_judges = [
        j for j in judges
        if gen_family is None or family_of(j) is None or family_of(j) != gen_family
    ]
    if len(usable_judges) < 2:
        raise HiveConfigError(
            f"Not enough judges after family exclusion (need >=2, have {len(usable_judges)})"
        )

    verdicts: List[Dict[str, str]] = []
    for judge in usable_judges:
        judge_prompt = (
            f"REFUTE:\nTask: {task}\nGeneration: {generation['text']}\n"
            "Provide critique. Start your response with 'VERDICT: PASS' or 'VERDICT: FAIL'."
        )
        resp = gateway_chat(judge, judge_prompt, **kw)
        if not resp.get("ok"):
            verdicts.append({"judge": judge, "verdict": "FAIL",
                             "critique": f"judge call failed: {resp.get('error')}"})
            continue
        text = resp.get("text", "")
        verdict, critique = "FAIL", text.strip()  # missing/garbled marker counts as FAIL
        lines = text.splitlines()
        for i, line in enumerate(lines):
            m = re.match(r"\s*verdict:\s*(pass|fail)\b[.:,]?\s*(.*)", line, re.I)
            if m:
                verdict = m.group(1).upper()
                critique = "\n".join([m.group(2)] + lines[i + 1:]).strip()
                break
        verdicts.append({"judge": judge, "verdict": verdict, "critique": critique})

    passes = sum(1 for v in verdicts if v["verdict"] == "PASS")
    return {"generation": generation, "verdicts": verdicts, "pass": passes > (len(verdicts) // 2)}


def log_run(record: Dict[str, Any]) -> None:
    """Append *record* as a JSON line to RUN_LOG. Never raises; warns on stderr."""
    try:
        RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
        with RUN_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"warning: run-log write failed: {e}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# Agentic-lane dispatch — the fleet's OWN session bus, not a completion endpoint.
# See docs/16-session-bus.md. This is a pure-Python client of that bus's documented
# HTTP API (POST /send, GET /poll) — no Node runtime dependency required.
# --------------------------------------------------------------------------- #


def agent_dispatch(
    task: str,
    to_machine: str,
    to_session: Optional[str] = None,
    timeout: int = 3600,
    wait_seconds: int = 25,
) -> Dict[str, Any]:
    """
    Send *task* to a live Claude Code session over the fleet-bus and poll for a reply.

    Requires FLEET_BUS_URL (default http://localhost:4100 — see docs/16-session-bus.md)
    and FLEET_MACHINE_NAME / FLEET_BUS_TOKEN if your bus server was started with a token.
    """
    bus = os.environ.get("FLEET_BUS_URL", "http://localhost:4100")
    my_machine = os.environ.get("FLEET_MACHINE_NAME", "hive-cli")
    my_session = os.environ.get("HIVE_BUS_SESSION", f"hive-{os.getpid()}")
    token = os.environ.get("FLEET_BUS_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Fleet-Token"] = token

    start = time.time()
    try:
        send_body = {
            "to": to_machine, "from": my_machine, "body": task,
            "to_session": to_session, "from_session": my_session,
        }
        req = urllib.request.Request(f"{bus}/send", data=json.dumps(send_body).encode(),
                                      headers=headers, method="POST")
        urllib.request.urlopen(req, timeout=30).read()

        while True:
            elapsed = int(time.time() - start)
            if elapsed > timeout:
                raise TimeoutError(f"agent dispatch: no reply from {to_machine} within {timeout}s")
            poll_url = f"{bus}/poll?machine={my_machine}&session={my_session}&waitSeconds={wait_seconds}"
            req = urllib.request.Request(poll_url, headers=headers, method="GET")
            body = json.loads(urllib.request.urlopen(req, timeout=wait_seconds + 10).read())
            if body:  # non-empty backlog
                return {"task": task, "to": to_machine, "result": body, "elapsed": elapsed}
    except Exception as e:
        return {"task": task, "to": to_machine, "error": str(e), "elapsed": int(time.time() - start)}


# --------------------------------------------------------------------------- #
# CLI command implementations
# --------------------------------------------------------------------------- #


def cmd_ask(args: argparse.Namespace) -> int:
    try:
        resp = gateway_chat(args.alias, args.prompt, max_tokens=args.max_tokens, task_type=args.task_type)
        if args.json:
            print(json.dumps(resp, ensure_ascii=False))
        elif resp["ok"]:
            print(resp["text"])
        else:
            print(f"Error: {resp['error']}", file=sys.stderr)
            return 1
        log_run({"ts": time.time(), "cmd": "ask", "alias": args.alias,
                 "latency_ms": resp.get("latency_ms"), "ok": resp.get("ok"),
                 "tokens_in": resp.get("tokens_in"), "tokens_out": resp.get("tokens_out")})
        return 0 if resp["ok"] else 1
    except HiveDenyError as e:
        print(f"Denied: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 3


def cmd_swarm(args: argparse.Namespace) -> int:
    try:
        aliases = [a.strip() for a in args.models.split(",") if a.strip()]
        if not aliases:
            print("Error: -m/--models needs at least one alias (comma-separated)", file=sys.stderr)
            return 2
        results = swarm(aliases, args.prompt, max_tokens=args.max_tokens)
        for alias, res in zip(aliases, results):
            if res["ok"]:
                print(f"[{alias}] {res['text']}")
            else:
                print(f"[{alias}] ERROR: {res['error']}", file=sys.stderr)
        log_run({"ts": time.time(), "cmd": "swarm", "aliases": aliases,
                 "latency_ms": max((r.get("latency_ms", 0) for r in results), default=0),
                 "ok": all(r["ok"] for r in results)})
        return 0 if all(r["ok"] for r in results) else 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2


def cmd_check(args: argparse.Namespace) -> int:
    try:
        result = check(args.gen, args.task)
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(f"Overall verdict: {'PASS' if result['pass'] else 'FAIL'}")
            for v in result["verdicts"]:
                print(f"- {v['judge']}: {v['verdict']}")
                print(f"  Critique: {v['critique']}")
        log_run({"ts": time.time(), "cmd": "check", "gen_alias": args.gen,
                 "task": args.task, "pass": result["pass"], "ok": True})
        return 0 if result["pass"] else 1
    except HiveConfigError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 3


def cmd_agent(args: argparse.Namespace) -> int:
    try:
        result = agent_dispatch(args.task, args.to, to_session=args.to_session, timeout=args.timeout)
        if "error" in result:
            print(f"Agent error: {result['error']}", file=sys.stderr)
            return 1
        print(json.dumps(result["result"], ensure_ascii=False))
        log_run({"ts": time.time(), "cmd": "agent", "task": args.task, "to": args.to,
                 "elapsed": result["elapsed"], "ok": True})
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2


def cmd_status(_args: argparse.Namespace) -> int:
    healthy = False
    try:
        with _urlopen(f"{GATEWAY}/health") as resp:
            healthy = resp.getcode() == 200
    except Exception:
        healthy = False

    try:
        with _urlopen(f"{GATEWAY}/v1/models") as resp:
            models_body = resp.read().decode()
    except Exception as e:
        models_body = f"Error fetching models: {e}"

    print("Gateway health:", "OK" if healthy else "UNHEALTHY", f"({GATEWAY})")
    print("Models response snippet:", models_body[:200].replace("\n", " "))

    try:
        with RUN_LOG.open("r", encoding="utf-8") as f:
            tail = list(deque(f, maxlen=10))  # bounded memory even on a huge log
        print("\nLast 10 run-log entries:")
        for line in tail:
            print(line, end="")
    except Exception:
        print("\nRun log not available.", file=sys.stderr)

    return 0 if healthy else 2


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hive", description="Fleet Hive orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ask = sub.add_parser("ask", help="Ask a single model")
    p_ask.add_argument("alias", help="Model alias from gateway-config.yaml")
    p_ask.add_argument("prompt", help="Prompt string")
    p_ask.add_argument("--max-tokens", type=int, default=4096, help="Maximum tokens")
    p_ask.add_argument("--json", action="store_true", help="Output raw JSON")
    p_ask.add_argument("--task-type", choices=["general", "citation", "research"],
                        default="general", help="Task type for deny-list enforcement")
    p_ask.set_defaults(func=cmd_ask)

    p_swarm = sub.add_parser("swarm", help="Concurrent calls to multiple models")
    p_swarm.add_argument("-m", "--models", required=True, help="Comma-separated aliases")
    p_swarm.add_argument("prompt", help="Prompt string")
    p_swarm.add_argument("--max-tokens", type=int, default=4096, help="Maximum tokens")
    p_swarm.set_defaults(func=cmd_swarm)

    p_check = sub.add_parser("check", help="Generate then have a cross-family judge panel evaluate it")
    p_check.add_argument("--gen", required=True, help="Generator alias")
    p_check.add_argument("task", help="Task description")
    p_check.add_argument("--json", action="store_true", help="Output raw JSON")
    p_check.set_defaults(func=cmd_check)

    p_agent = sub.add_parser("agent", help="Dispatch a task to a live Claude Code session over the fleet bus")
    p_agent.add_argument("task", help="Task description")
    p_agent.add_argument("--to", required=True, help="Target machine name")
    p_agent.add_argument("--to-session", default=None, help="Target session id (optional)")
    p_agent.add_argument("--timeout", type=int, default=3600, help="Timeout seconds")
    p_agent.set_defaults(func=cmd_agent)

    sub.add_parser("status", help="Gateway health and recent run log").set_defaults(func=cmd_status)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except HiveError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
