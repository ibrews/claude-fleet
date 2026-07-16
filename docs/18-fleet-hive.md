# Fleet Hive

[Model Routing](13-model-routing.md) answers *which single model* should handle a task. Fleet Hive answers a different question: once you have several machines and several cloud API keys, how do you get **many of them working at once** — in parallel, with automatic failover, and with model outputs checking each other's work — instead of one bespoke `curl` command at a time?

Fleet Hive is two small, separable pieces:

1. **A gateway** — [LiteLLM Proxy](https://github.com/BerriAI/litellm) (free, OSS), running on any always-on fleet machine, that puts every one of your completion lanes (local Ollama on N machines, Gemini, NVIDIA NIM, Groq, Cerebras, whatever you have keys for) behind one OpenAI-compatible endpoint with named aliases.
2. **A ~350-line orchestrator CLI** (`hive.py`, stdlib-only Python) that adds what a router alone can't do: parallel fan-out, and a cross-family adversarial judge panel.

Why a real gateway instead of a bigger script? Load-balancing, retries, cooldowns, and provider-specific error handling are exactly the kind of undifferentiated, fiddly plumbing a mature library already solves — reinventing it is a classic yak-shave. Keep your own code for the part that's actually specific to your fleet: which models judge which, and what they're allowed to touch.

---

## Setup

```bash
pip install 'litellm[proxy]'
cd scripts/hive
cp gateway-config.example.yaml gateway-config.yaml
# edit gateway-config.yaml: swap alpha/beta/gamma api_base lines for your
# actual Tailscale hostnames (see roster.md) and the models you have pulled
```

Add to your `.env` (alongside the keys already there — see root `.env.example`):

```bash
export HIVE_MASTER_KEY="pick-any-secret-string"   # gateway auth; matches HIVE_KEY below
export HIVE_KEY="pick-any-secret-string"          # same value, read by hive.py
# Optional extra lanes (only if you configured them in gateway-config.yaml):
export GROQ_API_KEY=""
export CEREBRAS_API_KEY=""
```

Start the gateway (pick any always-on machine — it does not need a GPU):

```bash
./launch-gateway.sh          # binds :4101 by default — NOT :4100, that's the session bus
```

Keep it running the same way you'd keep the session bus server alive (LaunchAgent / systemd unit / Task Scheduler) — see [Session Bus § Setup](16-session-bus.md#setup) for the pattern.

From any other machine, point at it:

```bash
export HIVE_GATEWAY="http://beta:4101"   # your gateway machine's Tailscale hostname
```

---

## The CLI

```bash
python3 scripts/hive/hive.py ask hive-fast "What's 2+2?"

python3 scripts/hive/hive.py swarm -m hive-fast,gemini-flash,nim-qwen3.5 \
  "Explain the CAP theorem in one sentence."

python3 scripts/hive/hive.py check --gen hive-coder \
  "Write a python function is_palindrome(s) that ignores case and non-alphanumerics."

python3 scripts/hive/hive.py agent "review the auth module for security issues" --to beta

python3 scripts/hive/hive.py status
```

| Command | What it does |
|---|---|
| `ask <alias> "<prompt>"` | One call through the gateway to a named alias |
| `swarm -m a,b,c "<prompt>"` | The SAME prompt to N aliases concurrently — see them agree or disagree |
| `check --gen <alias> "<task>"` | Generate with `<alias>`, then have a panel of judges (from *different* model families) try to refute it |
| `agent "<task>" --to <machine>` | Dispatch to a live Claude Code session on `<machine>` over [the session bus](16-session-bus.md) and wait for its reply |
| `status` | Gateway health, reachable models, last 10 run-log entries |

## The judge panel — cross-family, not self-grading

`check` is the piece a router alone doesn't give you. The rule it enforces: **a judge never shares a model family with the generator it's grading.** Ask `qwen2.5-coder` to write a function and let a `qwen`-family model grade it, and you've mostly just asked the model to agree with itself. `hive.py`'s `family_of()` keeps a small alias→family map (`ALIAS_FAMILY` in the script) precisely so a panel always spans genuinely different models — the example config ships with a Qwen-family generator judged by a GPT-OSS-family model and a Gemini-family model.

The panel majority-votes PASS/FAIL and returns each judge's critique, so a FAIL comes with a reason, not just a verdict.

## The deny-list pattern

`DENY_CITATION` in `hive.py` ships empty — it's a hook, not a policy. The idea: if you run your own model evals (or read someone else's) and find that a specific model confidently fabricates citations, sources, or facts on a certain task type while otherwise scoring well, you add it to the set once and every future `ask`/`check` call refuses it for `--task-type citation` or `research` calls — *before* any network round-trip, not after reading a wrong answer. You can deny a raw model string or a whole pool alias (if an alias load-balances across a model you don't trust for that task type, deny the alias itself — see the test suite for the exact pattern).

## Gotchas (found the hard way — save yourself the debugging)

- **LiteLLM does not forward Ollama's `think:false` parameter**, at either the config or the request level. A local reasoning model that needs it (e.g. DeepSeek-R1) will return **empty content** behind this gateway — call it directly instead, or keep it off the gateway entirely.
- **A client-side socket timeout does not bound total request time.** If the gateway itself hangs mid-retry (rather than erroring), a plain `urllib.request.urlopen(..., timeout=N)` can still block far past `N` seconds. `hive.py` wraps every gateway call in a hard total deadline via a worker-thread future — copy that pattern if you write your own client.
- **Fallback chains follow only one hop.** If `router_settings.fallbacks` sends alias A to fallback B, and B *also* needs a fallback, B needs its own chain-link entry in the list — the router does not walk the rest of A's original fallback list once it's inside B.
- **Some providers reject a bare Python User-Agent.** Cerebras's edge, specifically, returns a 403 to `python-urllib/3.x` — `hive.py` always sends a curl-style `User-Agent` header for exactly this reason.
- **Reasoning models can spend their entire output budget on hidden "thinking" tokens** (observed on Gemini 2.5 Pro/Flash and on GLM's flash-reasoning tier) and return empty content with `finishReason: MAX_TOKENS`. Give reasoning-tier aliases a generous `--max-tokens` — `hive.py`'s CLI default is already 4096 for this reason.

## Extending it

- **More lanes**: add a `model_list` entry per deployment; `os.environ/YOUR_KEY_NAME` for any secret.
- **More judges**: add entries to `ALIAS_FAMILY` in `hive.py` so `check` can tell them apart from your generators.
- **Your own agentic lane**: `agent_dispatch()` in `hive.py` is a ~30-line reference client for [the session bus's](16-session-bus.md) HTTP API — point it at any other dispatch mechanism you already have (a different message queue, a webhook, another CLI) by swapping that one function.

## What this is NOT

- Not a job queue — `swarm` blocks until every lane replies; there's no persistence or retry-later semantics across process restarts.
- Not a replacement for [Model Routing](13-model-routing.md)'s cost-tiering judgment — it's the plumbing that makes acting on that judgment in parallel practical.
- Not a way around the honesty of the underlying models — the deny-list only blocks models *you've already caught* being unreliable; it's a seatbelt, not a guarantee.
