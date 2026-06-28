# Model Routing

When running a fleet of Claude Code agents, managing API costs and latency is critical. The core principle of efficient agent orchestration is simple: **always route tasks to the cheapest model that can complete the job correctly.** 

By dynamically matching task complexity with the appropriate model tier, you minimize resource usage while maintaining high accuracy and performance.

---

## The Three Routing Tiers

To balance cost, privacy, latency, and capability, classify your agent workflows into three distinct tiers:

| Tier | Provider & Keys | Cost & Latency | Best Use Cases | Typical Tasks |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 1: Local** | Ollama (Local machine) | Free / Zero Latency | Mechanical tasks, sensitive data, offline work | Syntax checking, formatting, minor data extraction, boilerplate |
| **Tier 2: Mid-Tier** | Gemini 2.5 Flash (`GEMINI_API_KEY`) & NVIDIA NIM (`NVIDIA_API_KEY`) | Ultra-low cost / Fast | High-volume research, drafting, bulk code generation | Summarization, codebase search, drafting documentation, generic coding (134+ models) |
| **Tier 3: Premium** | Claude (`ANTHROPIC_API_KEY`) | Premium / Standard | Core logic, orchestration, complex architecture | System design, final reviews, multi-file refactoring, debugging |

---

## The Confidence Threshold Rule

To determine when a cheaper tier can handle a task autonomously, apply the **Confidence Threshold Rule**:

*   **90%+ Confidence:** Auto-dispatch to Tier 1 or Tier 2 without user intervention.
*   **70%–89% Confidence:** Ask the operator for approval first before dispatching to Tier 1 or Tier 2.
*   **Below 70% Confidence:** Do not attempt lower tiers. Escalate the task immediately to Tier 3 (Claude).

---

## Claude Internal Tiers

Within Claude itself, match the specific model to the current execution phase:

| Model | When to use |
|-------|-------------|
| **Haiku 4.5** | Mechanical edits, file moves, status checks, formatting |
| **Sonnet 4.6** *(default)* | Feature implementation, build loops, refactors, code review (~80% of tasks) |
| **Opus 4.8 / Fable 5** | Novel architecture, subtle cross-system root causes, ambiguous requirements |

**Inverting heuristic:** start on Sonnet; escalate to Opus only when Sonnet stalls twice on the same root cause.

> **Key Rule: Suggest downgrades in-session.** When the current Claude tier is overqualified for the task at hand, say so in one line and continue — e.g. *"This is a Sonnet task — consider `/model sonnet` to save Opus budget. Proceeding either way."* The user switches models with `/model`; Claude can't self-downgrade. The practice saves significant token spend over a long session.

---

## Practical Integration Examples

Configure your keys in your shell profile (e.g., `~/.zshrc`) or a local `.env` file:
```bash
export GEMINI_API_KEY="your-gemini-key"
export NVIDIA_API_KEY="your-nvidia-key"
export ANTHROPIC_API_KEY="your-anthropic-key"
```

### 1. Calling Gemini (Tier 2) via CLI
For fast summarization or research queries, use the `gemini` CLI:
```bash
GEMINI_API_KEY=$GEMINI_API_KEY gemini -p "Summarize the changes in src/" -y
```

### 2. Calling NVIDIA NIM (Tier 2) via curl
To generate bulk boilerplate using specialized coding models (such as `meta/llama-4-maverick-17b-128e-instruct` or `openai/gpt-oss-120b`):
```bash
curl -X POST "https://integrate.api.nvidia.com/v1/chat/completions" \
  -H "Authorization: Bearer $NVIDIA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "meta/llama-4-maverick-17b-128e-instruct",
    "messages": [{"role": "user", "content": "Write a python script to parse logs."}]
  }'
```

### 3. Calling Local Ollama (Tier 1)
Run tasks completely locally and offline using Ollama:
```bash
# Interactive CLI
ollama run llama3

# REST API Query
curl -X POST "http://localhost:11434/api/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3",
    "prompt": "Check this regex pattern for syntax errors: ^[a-z]+$",
    "stream": false
  }'
```
