# Session Bus

Real-time "tap on the shoulder" messaging between live Claude Code sessions on different machines. A session on `alpha` can message a session on `beta` mid-run — "this doesn't make sense", "you have stale data", "let's figure this out together" — and it lands in the target session's transcript within about a second.

## Where this fits

Three ways machines in your fleet can talk to each other, each with a different tradeoff:

| | Inbox System (docs 05) | Session Bus (this doc) | Control Center (docs 11) |
|---|---|---|---|
| Delivery | Async — next session start | Real-time if listening, else queued | Real-time (dashboard + dispatch) |
| Durability | Durable (git-committed) | Ephemeral (in-memory, cleared on restart) | Durable (SQLite) |
| Needs a listener? | No — works with nobody around | For instant delivery; otherwise queues | No — it's a dashboard |
| Best for | Work orders, must-not-be-lost tasks | Live coordination, mid-session chatter | Fleet-wide visibility, instant dispatch |
| Infra required | None (just git) | One small always-on process | Node + Express + SQLite dashboard |

Use the bus for the kind of thing you'd say out loud if the other session's operator were standing next to you. Use the inbox for anything that has to survive nobody reading it for a week. If you already run a Control Center, the bus is the lightweight real-time layer it doesn't otherwise have — see [Why not just use the Control Center?](#why-not-just-use-the-control-center) below.

## Architecture

```
alpha (sends)                    fleet-bus-server.js                beta (listens)
node fleet-bus-client.js   ──POST /send──▶  in-memory queue   ──long-poll──▶  node fleet-bus-client.js listen
  send --to beta                 + live push                                  (armed via Claude Code's Monitor tool)
                                                                                     │
                                                                              message appears in
                                                                              the session's transcript
```

The server (`scripts/fleet-bus-server.js`) is a single file with **zero npm dependencies** — just Node's built-in `http` module. Run it once on any always-on machine in your fleet (a spare box, a cloud VM, the same host as your Control Center if you have one).

Delivery is long-poll, not WebSocket, on purpose — see [Why long-poll, not WebSocket](#why-long-poll-not-websocket).

## Setup

### 1. Start the server

On any always-on machine:

```bash
node scripts/fleet-bus-server.js --port 4100
# or: PORT=4100 node scripts/fleet-bus-server.js
```

Keep it running the same way you'd keep any small service alive — a LaunchAgent (macOS), a systemd unit (Linux), or Task Scheduler (Windows). It's stateless and cheap; a restart just clears the ephemeral message queue.

Optional auth: set `FLEET_BUS_TOKEN` before starting the server, and every sender must pass a matching `X-Fleet-Token` header (the client reads it from the same env var). Unset by default — like the rest of claude-fleet, this assumes a private Tailscale mesh as the trust boundary. Reads (`/poll`, `/sessions`, `/messages`, `/health`) are never gated.

### 2. Point every machine at it

```bash
export FLEET_BUS_URL=http://<server-tailscale-ip>:4100
# and, if the server has a token:
export FLEET_BUS_TOKEN=<the token>
```

Add both to your shell profile. `FLEET_MACHINE_NAME` (already used by the inbox scripts, see [docs/07-hooks.md](07-hooks.md)) is reused here too — the client identifies itself with it.

## Usage

### Send a message

```bash
node scripts/fleet-bus-client.js send --to beta --body "your build looks stale, can you re-pull?" --session my-session-id
```

- `--to` is a machine name. Add `--to-session <id>` to target one specific session on that machine instead of any session listening for it.
- `--session <id>` identifies *you* as the sender, so the other side can reply directly to you. Anything stable and descriptive works.
- The client prints `delivered live` (a session was listening right now) or `queued` (it'll deliver the moment one starts listening).

### Be reachable — arm a listener

This is the receive side, and it's meant to run under Claude Code's `Monitor` tool in **command mode**:

```
Monitor({
  command: "node scripts/fleet-bus-client.js listen --session <my-session-id>",
  description: "fleet bus messages",
  persistent: true, timeout_ms: 3600000
})
```

Arm this once at the start of any session where being interruptible matters — a long-running build, an overnight loop, anything another machine might need to weigh in on. Each incoming message becomes a notification in the transcript, and **listening while idle costs zero tokens** — the harness handles the wait outside your context window.

Don't use `Monitor`'s native `ws:` mode against this server. See the gotcha below.

### Who's listening right now / message history

```bash
node scripts/fleet-bus-client.js sessions             # fleet-wide "who's armed"
node scripts/fleet-bus-client.js history --machine beta  # last 50 messages (debugging)
```

## Messaging a human (Telegram, optional)

`--to human` is a reserved target: nobody will ever poll as machine "human", so instead of queuing forever, the server relays it to Telegram via [fleet-bot](../telegram/fleet-bot/) — reusing fleet-bot's own bot, no second bot needed. Entirely optional: with no `~/claude-fleet/fleet.env`, `--to human` just queues silently (harmless, just means nobody's set up the relay yet).

```bash
node scripts/fleet-bus-client.js send --to human --body "..." --session my-id
```

Use it when a session is about to finish ambiguous or non-trivial work and there's a real chance the operator would want to redirect before it actually stops — send a summary, then arm a **bounded** listener (a few minutes, not the long-running window used for active collaboration) instead of exiting immediately. A reply within the window delivers live through the bus; nothing arrives, the listener just times out and the session finishes stopping normally.

**Replying from Telegram** works the same way turn-guard replies already do — fleet-bot tags the relayed message `#sid=/#machine=`, and replying to it in Telegram routes back through the bus if the session is still listening (instant, and reaches Windows machines fleet-bot's SSH `claude --resume` path can't), or falls back to `claude --resume` if it's already stopped. See [telegram/fleet-bot/README.md](../telegram/fleet-bot/README.md).

`/sessions` and `/msg <machine> <text>` are also available directly in Telegram once fleet-bot is set up — no reply-thread needed.

## API Reference

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/send` | `{to, from, to_session?, from_session?, body}` (≤4000 chars) — token-gated if `FLEET_BUS_TOKEN` is set |
| `GET` | `/poll` | `?machine=&session=&waitSeconds=` — long-poll receive, used by `listen` |
| `GET` | `/sessions` | Currently-listening sessions, fleet-wide |
| `GET` | `/messages` | Last 50 messages, optional `?machine=` filter |
| `GET` | `/health` | `{ok, messages, listeners}` |

## Gotcha: don't use Monitor's `ws:` mode

Claude Code's `Monitor` tool has a native WebSocket mode (`Monitor({ws: {url: ...}})`). Against a server reachable only over a private mesh like Tailscale, it will typically fail — the harness's SSRF guard blocks CGNAT-range IPs (Tailscale's `100.64.0.0/10`), and it resolves MagicDNS-style hostnames back to the blocked IP before you ever get a connection. That's why `fleet-bus-client.js listen` long-polls a plain HTTP endpoint instead of opening a socket: it's the path that actually works from inside a Claude Code session, and it has the added benefit of zero npm dependencies.

## Why long-poll, not WebSocket

Beyond the Monitor gotcha above: long-polling over plain `http` needs nothing beyond what Node ships with, works through any proxy or firewall that already lets HTTP through, and the client/server are each under 200 lines. A `ws`-based version would need a dependency this repo otherwise has zero of (see `package.json`), for a latency difference (sub-second either way) nobody doing session coordination will notice.

## Why not just use the Control Center?

If you already run the [Control Center](11-control-center.md), you might wonder why this isn't just another endpoint on it. Two reasons it's kept separate:

1. **The Control Center's server isn't included in this repo** (see docs 11) — you build or obtain your own. The session bus is meant to work standalone, with nothing else running, so it ships as a real, runnable reference implementation instead of an API spec.
2. **Different durability model.** The Control Center persists to SQLite because dispatch history and machine state should survive a restart. The bus is deliberately ephemeral — it's for the kind of message that's only useful in the next few minutes anyway, and keeping it out of any database (or git) is what keeps `inbox/` from turning into a chat log.

If you do run both, nothing stops you from adding `fleet-bus-server.js`'s routes to your Control Center's Express app — the code is small enough to read in five minutes and port.

## Related

- [Inbox System](05-inbox-system.md) — the durable, no-listener-required async channel
- [Hooks](07-hooks.md) — where `FLEET_MACHINE_NAME` and friends come from
- [Control Center](11-control-center.md) — the heavier, durable, dashboard-driven alternative
