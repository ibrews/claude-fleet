#!/usr/bin/env python3
"""Static dashboard generator for the Command Center — v2 (briefing edition).

Two content layers, each with its own visible staleness stamp:

  1. BRIEFING (briefing.json, AI-authored at checkpoints) — the narrative a
     cold reader needs: north star, per-phase progress, topic Q&As, unsolved
     problems, ranked recommendations, checkpoint timeline. Written for
     someone who has NOT been tracking the project.
  2. MECHANICAL (reconcile.py, regenerated every cycle) — live sessions,
     open/blocked/done triggers, anomalies, inbox items.

Visual language: tungsten-amber + gel-teal on a dark purple-tinted ground,
monospace kickers, status pills (proven/live/blocked/planned), phase-board
rows, recommendation callout. Light + dark via prefers-color-scheme AND
data-theme overrides. Sections are collapsible (<details>) — glanceable
first, drill-down second.

Also renders the INDEX page listing every instance (for wherever you mount
the state repo as a static site — see README's "Publishing the dashboard").

If briefing.json is absent the page degrades to mechanical-only with a hint —
keeps the engine fork-clean for projects that haven't written a briefing yet.
"""
import html
import json
import os
import time

CSS = """
:root{
  --ground:#15111b;--surface:#1e1826;--raised:#29212f;--border:#392f45;--border-soft:#2c2436;
  --ink:#ece7f0;--ink-dim:#a99fb5;--ink-faint:#7d7488;
  --amber:#f0a94b;--gel:#59c7c1;--proven:#5cc98b;--live:#f0a94b;--blocked:#ef6b64;--planned:#6f6679;
  --shadow:0 1px 0 rgba(255,255,255,.03) inset,0 8px 24px -12px rgba(0,0,0,.6);--maxw:1180px;
}
@media (prefers-color-scheme: light){:root{
  --ground:#f4efe8;--surface:#fbf8f3;--raised:#ffffff;--border:#ddd3c6;--border-soft:#e7ded2;
  --ink:#251d2e;--ink-dim:#6a6072;--ink-faint:#9990a2;
  --amber:#c07a17;--gel:#1a8a84;--proven:#1f9d5e;--live:#c07a17;--blocked:#cf4139;--planned:#9990a2;
  --shadow:0 1px 0 rgba(255,255,255,.6) inset,0 10px 26px -16px rgba(60,40,20,.35);
}}
:root[data-theme="dark"]{
  --ground:#15111b;--surface:#1e1826;--raised:#29212f;--border:#392f45;--border-soft:#2c2436;
  --ink:#ece7f0;--ink-dim:#a99fb5;--ink-faint:#7d7488;
  --amber:#f0a94b;--gel:#59c7c1;--proven:#5cc98b;--live:#f0a94b;--blocked:#ef6b64;--planned:#6f6679;
}
:root[data-theme="light"]{
  --ground:#f4efe8;--surface:#fbf8f3;--raised:#ffffff;--border:#ddd3c6;--border-soft:#e7ded2;
  --ink:#251d2e;--ink-dim:#6a6072;--ink-faint:#9990a2;
  --amber:#c07a17;--gel:#1a8a84;--proven:#1f9d5e;--live:#c07a17;--blocked:#cf4139;--planned:#9990a2;
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;line-height:1.5;-webkit-font-smoothing:antialiased}
.mono{font-family:ui-monospace,"SF Mono",Menlo,monospace}
.wrap{max-width:var(--maxw);margin:0 auto;padding:0 24px 72px}
a{color:var(--gel)}
.mast{padding:38px 0 26px;border-bottom:1px solid var(--border);display:grid;grid-template-columns:1fr auto;gap:24px;align-items:end}
.kicker{font-family:ui-monospace,monospace;font-size:11px;letter-spacing:.28em;text-transform:uppercase;color:var(--amber);margin:0 0 10px}
h1{font-size:clamp(30px,5vw,50px);line-height:.98;margin:0;font-weight:800;letter-spacing:-.03em}
h1 .b{color:var(--amber)}
.northstar{margin:14px 0 0;max-width:52ch;color:var(--ink-dim);font-size:15px}
.northstar b{color:var(--ink);font-weight:600}
.mast-meta{text-align:right;font-family:ui-monospace,monospace;font-size:11.5px;color:var(--ink-faint)}
.mast-meta .now{color:var(--ink-dim)}
.pulse{display:inline-flex;align-items:center;gap:7px;margin-top:10px;padding:5px 11px;border:1px solid var(--border);border-radius:999px;background:var(--surface);font-size:11.5px;color:var(--ink-dim)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--live);box-shadow:0 0 0 3px color-mix(in srgb,var(--live) 22%,transparent)}
@keyframes breathe{0%,100%{opacity:1}50%{opacity:.45}}
@media (prefers-reduced-motion: no-preference){.dot{animation:breathe 2.4s ease-in-out infinite}}
section,details.sec{margin-top:34px}
.sec-head{display:flex;align-items:baseline;gap:14px;margin:0 0 14px}
.sec-head h2{font-size:13px;letter-spacing:.16em;text-transform:uppercase;margin:0;color:var(--ink);font-weight:700}
.sec-head .rule{flex:1;height:1px;background:var(--border-soft)}
.sec-head .note{font-family:ui-monospace,monospace;font-size:11px;color:var(--ink-faint)}
details.sec>summary{list-style:none;cursor:pointer;user-select:none}
details.sec>summary::-webkit-details-marker{display:none}
details.sec>summary .sec-head{margin-bottom:0}
details.sec[open]>summary .sec-head{margin-bottom:14px}
details.sec>summary .tw{font-family:ui-monospace,monospace;font-size:11px;color:var(--ink-faint)}
details.sec>summary .tw::before{content:"▸ "}
details.sec[open]>summary .tw::before{content:"▾ "}
.pill{display:inline-flex;align-items:center;gap:6px;white-space:nowrap;font-family:ui-monospace,monospace;font-size:10.5px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;padding:3px 9px;border-radius:999px;border:1px solid}
.pill::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}
.pill.proven{color:var(--proven);border-color:color-mix(in srgb,var(--proven) 40%,transparent);background:color-mix(in srgb,var(--proven) 12%,transparent)}
.pill.live{color:var(--live);border-color:color-mix(in srgb,var(--live) 42%,transparent);background:color-mix(in srgb,var(--live) 13%,transparent)}
.pill.blocked{color:var(--blocked);border-color:color-mix(in srgb,var(--blocked) 42%,transparent);background:color-mix(in srgb,var(--blocked) 13%,transparent)}
.pill.planned{color:var(--planned);border-color:color-mix(in srgb,var(--planned) 40%,transparent);background:color-mix(in srgb,var(--planned) 10%,transparent)}
.pill.partial{color:var(--amber);border-color:color-mix(in srgb,var(--amber) 42%,transparent);background:color-mix(in srgb,var(--amber) 13%,transparent)}
.board{border:1px solid var(--border);border-radius:14px;overflow:hidden;background:var(--surface);box-shadow:var(--shadow)}
.row{display:grid;grid-template-columns:34px minmax(0,1.4fr) 108px 130px 1fr;gap:14px;align-items:start;padding:14px 18px;border-top:1px solid var(--border-soft)}
.row:first-child{border-top:none}
.row .ph-n{font-family:ui-monospace,monospace;font-size:12.5px;color:var(--ink-faint);font-weight:600;padding-top:1px}
.row .ph-name{font-weight:640;font-size:14px}
.row .ph-name small{display:block;font-weight:400;color:var(--ink-faint);font-size:11px;margin-top:2px;font-family:ui-monospace,monospace}
.row .ph-state{font-size:12.5px;color:var(--ink-dim)}
.row .ph-state em{color:var(--ink);font-style:normal;font-weight:600}
.bar{height:6px;border-radius:99px;background:var(--raised);border:1px solid var(--border-soft);overflow:hidden;margin-top:6px}
.bar i{display:block;height:100%;border-radius:99px}
.bar.proven i{background:var(--proven)}.bar.live i{background:var(--live)}.bar.blocked i{background:var(--blocked)}.bar.planned i{background:var(--planned)}
.bar-lbl{font-family:ui-monospace,monospace;font-size:10.5px;color:var(--ink-faint);margin-top:3px}
.bigbars{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:18px}
.bigbar{border:1px solid var(--border);border-radius:12px;background:var(--surface);box-shadow:var(--shadow);padding:14px 16px}
.bigbar .t{font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-dim);font-weight:600}
.bigbar .n{font-size:26px;font-weight:800;margin:2px 0 6px}
.bigbar .n small{font-size:12px;color:var(--ink-faint);font-weight:400}
.bigbar .bar{height:9px}
.bigbar .why{font-size:11px;color:var(--ink-faint);margin-top:7px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:22px}
.panel{border:1px solid var(--border);border-radius:14px;background:var(--surface);box-shadow:var(--shadow);padding:18px 20px}
.panel h3{margin:0 0 4px;font-size:13px;letter-spacing:.12em;text-transform:uppercase}
.panel .sub{margin:0 0 14px;font-size:12px;color:var(--ink-faint);font-family:ui-monospace,monospace}
ul.clean{list-style:none;margin:0;padding:0;display:grid;gap:11px}
ul.clean li{display:grid;grid-template-columns:auto 1fr;gap:10px;align-items:start;font-size:13px}
ul.clean li .who{font-family:ui-monospace,monospace;font-size:10.5px;color:var(--gel);background:color-mix(in srgb,var(--gel) 12%,transparent);border:1px solid color-mix(in srgb,var(--gel) 30%,transparent);padding:2px 7px;border-radius:6px;white-space:nowrap;align-self:start}
ul.clean li .what{color:var(--ink-dim)}
ul.clean li .what b{color:var(--ink);font-weight:600}
.rec{border:1px solid var(--border);border-left:3px solid var(--amber);border-radius:12px;background:linear-gradient(180deg,color-mix(in srgb,var(--amber) 6%,var(--surface)),var(--surface));padding:18px 22px}
.rec ol{margin:0;padding-left:0;list-style:none;display:grid;gap:13px;counter-reset:rec}
.rec ol li{display:grid;grid-template-columns:30px 1fr;gap:12px;font-size:13.5px;color:var(--ink-dim)}
.rec ol li::before{counter-increment:rec;content:counter(rec);font-family:ui-monospace,monospace;font-weight:700;font-size:14px;color:var(--amber);border:1px solid color-mix(in srgb,var(--amber) 40%,transparent);border-radius:8px;width:28px;height:28px;display:flex;align-items:center;justify-content:center}
.rec ol li b{color:var(--ink);display:block;margin-bottom:2px}
.rec ol li .un{font-family:ui-monospace,monospace;font-size:10.5px;color:var(--amber);margin-top:4px;display:block}
details.topic{border:1px solid var(--border);border-radius:12px;background:var(--surface);box-shadow:var(--shadow);margin-top:10px;overflow:hidden}
details.topic>summary{list-style:none;cursor:pointer;display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center;padding:13px 16px;font-weight:600;font-size:13.5px}
details.topic>summary::-webkit-details-marker{display:none}
details.topic>summary::after{content:"▸";color:var(--ink-faint);grid-column:3}
details.topic[open]>summary::after{content:"▾"}
details.topic .a{padding:0 16px 15px;font-size:13px;color:var(--ink-dim);border-top:1px solid var(--border-soft);padding-top:12px}
.tl{list-style:none;margin:0;padding:0;display:grid;gap:0}
.tl li{display:grid;grid-template-columns:96px 14px 1fr;gap:12px;align-items:start;font-size:13px;padding:9px 0}
.tl li .d{font-family:ui-monospace,monospace;font-size:11.5px;color:var(--amber);text-align:right;padding-top:1px}
.tl li .k{position:relative}
.tl li .k::before{content:"";position:absolute;left:3px;top:7px;width:8px;height:8px;border-radius:50%;background:var(--amber)}
.tl li:not(:last-child) .k::after{content:"";position:absolute;left:6.5px;top:17px;bottom:-14px;width:1px;background:var(--border)}
.tl li .w{color:var(--ink-dim)}
.stat-strip{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}
.stat-strip span{font-family:ui-monospace,monospace;font-size:11.5px;color:var(--ink-dim);padding:6px 11px;border:1px solid var(--border-soft);border-radius:8px;background:var(--surface)}
.stat-strip span b{color:var(--ink)}
.stale{display:inline-block;font-family:ui-monospace,monospace;font-size:10.5px;color:var(--blocked);border:1px solid color-mix(in srgb,var(--blocked) 40%,transparent);border-radius:6px;padding:2px 7px;margin-left:8px}
footer{margin-top:44px;padding-top:18px;border-top:1px solid var(--border-soft);font-family:ui-monospace,monospace;font-size:11px;color:var(--ink-faint);display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}
.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:18px;margin-top:20px}
.icard{border:1px solid var(--border);border-radius:14px;background:var(--surface);box-shadow:var(--shadow);padding:20px;display:block;color:inherit;text-decoration:none}
.icard h2{margin:0 0 6px;font-size:19px;font-weight:750}
.icard .desc{font-size:13px;color:var(--ink-dim);margin:0 0 12px}
.icard .meta{font-family:ui-monospace,monospace;font-size:11px;color:var(--ink-faint);margin-top:10px}
@media (max-width:820px){.mast{grid-template-columns:1fr}.mast-meta{text-align:left}.cols,.bigbars{grid-template-columns:1fr}.row{grid-template-columns:26px 1fr}.row>*{grid-column:2}.row .ph-n{grid-column:1}}
"""


def _e(s):
    return html.escape(str(s or ""))


def _sec(title, body_html, note="", open_=True, count=None):
    """A collapsible section styled like the artifact's sec-head."""
    n = f'<span class="note">{_e(note)}</span>' if note else ""
    c = f" ({count})" if count is not None else ""
    return (
        f'<details class="sec"{" open" if open_ else ""}><summary><div class="sec-head">'
        f'<h2>{_e(title)}{c}</h2><span class="rule"></span>{n}<span class="tw">toggle</span>'
        f"</div></summary>{body_html}</details>"
    )


def _pill(status):
    cls = status if status in ("proven", "live", "blocked", "planned", "partial") else "planned"
    label = {"live": "live edge"}.get(status, status)
    return f'<span class="pill {cls}">{_e(label)}</span>'


def _briefing_age_days(briefing):
    try:
        t = time.strptime(briefing["updated_at"][:10], "%Y-%m-%d")
        return int((time.time() - time.mktime(t)) / 86400)
    except Exception:
        return None


def render(state, briefing, ledger_summary):
    generated = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    b = briefing or {}
    name = state["instance"]

    # ---- masthead ----
    title_html = _e(name.replace("-", " ").title())
    parts = title_html.rsplit(" ", 1)
    if len(parts) == 2:
        title_html = f'{parts[0]} <span class="b">{parts[1]}</span>'
    age = _briefing_age_days(b)
    stale_chip = f'<span class="stale">briefing {age}d old — may lag reality</span>' if (age is not None and age > 3) else ""
    mast = f"""
<header class="mast"><div>
  <p class="kicker">Command Center · Program Briefing</p>
  <h1>{title_html}</h1>
  {f'<p class="northstar">{_e(b.get("north_star"))}</p>' if b.get("north_star") else ""}
</div><div class="mast-meta">
  <div class="now">live state {generated}</div>
  {f'<div>briefing as of {_e(b.get("updated_at","")[:10])}{stale_chip}</div>' if b else '<div>no briefing yet — mechanical view only</div>'}
  {f'<div class="pulse"><span class="dot"></span> live edge: {_e(b.get("live_edge"))}</div>' if b.get("live_edge") else ""}
</div></header>"""

    # ---- glance: one-liner + big progress bars ----
    glance = ""
    if b.get("one_liner_now"):
        glance += f'<p class="northstar" style="max-width:none;margin-top:20px"><b>Where we are:</b> {_e(b["one_liner_now"])}</p>'
    pr = b.get("progress") or {}
    if pr:
        glance += f"""
<div class="bigbars">
  <div class="bigbar"><div class="t">To first milestone</div>
    <div class="n">{pr.get("to_first_show_pct", 0)}<small>%</small></div>
    <div class="bar live"><i style="width:{pr.get("to_first_show_pct", 0)}%"></i></div>
    <div class="why">{_e(pr.get("to_first_show_note"))}</div></div>
  <div class="bigbar"><div class="t">Full roadmap</div>
    <div class="n">{pr.get("full_roadmap_pct", 0)}<small>%</small></div>
    <div class="bar planned"><i style="width:{pr.get("full_roadmap_pct", 0)}%;background:var(--gel)"></i></div>
    <div class="why">{_e(pr.get("full_roadmap_note"))}</div></div>
</div>"""

    # ---- recommendations ----
    recs_html = ""
    if b.get("recommendations"):
        items = ""
        for r in sorted(b["recommendations"], key=lambda r: r.get("rank", 99)):
            un = f'<span class="un">unblocks: {_e(r["unblocks"])}</span>' if r.get("unblocks") else ""
            # Single wrapper span: a bare text node after </b> would become its own
            # anonymous grid item and wrap one-word-per-line in the number column.
            items += f'<li><span><b>{_e(r["title"])}</b>{_e(r["detail"])}{un}</span></li>'
        recs_html = _sec("What we should do next — PM recommendations",
                         f'<div class="rec"><ol>{items}</ol></div>',
                         note="ranked · AI project manager's call, argue with it")

    # ---- phase board with bars ----
    phases_html = ""
    if b.get("phases"):
        rows = ""
        for p in b["phases"]:
            pct = int(p.get("pct", 0))
            rows += f"""<div class="row">
  <div class="ph-n">{_e(p["id"])}</div>
  <div><div class="ph-name">{_e(p["name"])}<small>{_e(p.get("subtitle"))}</small></div></div>
  <div>{_pill(p.get("status", "planned"))}</div>
  <div><div class="bar {p.get("status", "planned")}"><i style="width:{pct}%"></i></div><div class="bar-lbl">{pct}%</div></div>
  <div class="ph-state">{_e(p.get("state"))}</div>
</div>"""
        phases_html = _sec("Roadmap", f'<div class="board">{rows}</div>',
                           note="phases · status · progress · current state")

    # ---- topics (the "what's the latest on…" Q&As) ----
    topics_html = ""
    if b.get("topics"):
        cards = "".join(
            f'<details class="topic"><summary>{_e(t["q"])} {_pill(t.get("status", "partial"))}</summary>'
            f'<div class="a">{_e(t["a"])}</div></details>'
            for t in b["topics"]
        )
        topics_html = _sec("Questions, answered", cards,
                           note="click a question — written for someone who hasn't been tracking the project",
                           count=len(b["topics"]))

    # ---- problems ----
    problems_html = ""
    if b.get("problems"):
        items = "".join(
            f'<li><span class="who">{_e(p.get("phase", "?"))}</span>'
            f'<span class="what"><b>{_e(p["title"])}</b> — {_e(p["detail"])}</span></li>'
            for p in b["problems"]
        )
        problems_html = _sec("Biggest unsolved problems",
                             f'<div class="panel"><ul class="clean">{items}</ul></div>',
                             count=len(b["problems"]))

    # ---- checkpoint timeline ----
    timeline_html = ""
    if b.get("checkpoints"):
        items = "".join(
            f'<li><span class="d">{_e(c["date"])}</span><span class="k"></span><span class="w">{_e(c["label"])}</span></li>'
            for c in reversed(b["checkpoints"])
        )
        timeline_html = _sec("Checkpoint timeline",
                             f'<div class="panel"><ul class="tl">{items}</ul></div>',
                             note="newest first", open_=False)

    # ---- mechanical layer ----
    tw = state.get("tracked_workers", [])
    status_pill = {"live": "proven", "blocked": "blocked", "trigger open": "live", "no current activity": "planned"}
    tw_items = "".join(
        f'<li><span class="who">{_e(w["repo"])}</span><span class="what"><b>{_e(w["name"])}</b> — {_e(w["note"])} '
        f'{_pill(status_pill.get(w["status"], "planned"))}</span></li>'
        for w in tw
    )
    anomalies = [s for s in state["sessions_stale_or_dead"] if s.get("claim")]
    mech_body = f"""
<div class="stat-strip">
  <span><b>{len(state["triggers_in_flight"])}</b> in flight</span>
  <span><b>{len(state["triggers_blocked"])}</b> blocked</span>
  <span><b>{len(state["triggers_done"])}</b> done recently</span>
  <span><b>{len(state["sessions_live"])}</b> live sessions</span>
  <span><b>{len(anomalies)}</b> anomalies</span>
  <span><b>{len(state["inbox_open"])}</b> open inbox items</span>
</div>
<div class="cols" style="margin-top:16px">
  <div class="panel"><h3>Tracked workers</h3><p class="sub">named roster · cross-referenced against live sessions + triggers</p>
    <ul class="clean">{tw_items or '<li><span class="what">none configured</span></li>'}</ul></div>
  <div class="panel"><h3>Work in flight</h3><p class="sub">open triggers · claimant or target</p>
    <ul class="clean">{"".join(f'<li><span class="who">{_e(t.get("claimed_by") or t.get("target") or "?")}</span><span class="what">{_e(t["title"] or t["id"])}</span></li>' for t in state["triggers_in_flight"]) or '<li><span class="what">nothing in flight</span></li>'}</ul></div>
  <div class="panel"><h3>Blocked</h3><p class="sub">needs something before it can move</p>
    <ul class="clean">{"".join(f'<li><span class="who">{_e(t.get("target") or "?")}</span><span class="what">{_e(t["title"] or t["id"])}</span></li>' for t in state["triggers_blocked"]) or '<li><span class="what">nothing blocked</span></li>'}</ul></div>
  <div class="panel"><h3>Recently done · anomalies</h3><p class="sub">completions and abandoned claims</p>
    <ul class="clean">
      {"".join(f'<li><span class="who">✓ {_e(t.get("claimed_by") or "")}</span><span class="what">{_e(t["title"] or t["id"])}</span></li>' for t in state["triggers_done"])}
      {"".join(f'<li><span class="who" style="color:var(--blocked);border-color:color-mix(in srgb,var(--blocked) 30%,transparent);background:color-mix(in srgb,var(--blocked) 12%,transparent)">⚠ {_e(s["machine"])}</span><span class="what">claims "{_e(s["claim"])}" but {"process gone" if not s["pid_alive"] else "stale heartbeat"} ({s["heartbeat_age_min"]}m)</span></li>' for s in anomalies)}
    </ul></div>
</div>"""
    mech_html = _sec("Live now — sessions, triggers, anomalies", mech_body,
                     note=f"mechanical · regenerated every cycle · {ledger_summary}", open_=False)

    # ---- links ----
    links_html = ""
    if b.get("links"):
        chips = "".join(
            f'<span><a href="{_e(l["url"])}" target="_blank">{_e(l["label"])} ↗</a></span>' if l.get("url")
            else f'<span>{_e(l["label"])}: <span class="mono">{_e(l["path"])}</span></span>'
            for l in b["links"]
        )
        links_html = f'<div class="stat-strip" style="margin-top:30px">{chips}</div>'

    hint = "" if b else ('<div class="panel" style="margin-top:24px"><p class="sub">No briefing.json yet for this '
                         "instance — this page is mechanical state only. An AI session with project context writes "
                         "the briefing (north star, progress, topics, recommendations) at checkpoints; see the "
                         "engine README.</p></div>")

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(name)} — Command Center</title>
<style>{CSS}</style></head><body><div class="wrap">
{mast}{glance}{hint}
{recs_html}{phases_html}{topics_html}{problems_html}{timeline_html}{mech_html}{links_html}
<footer><span>{_e(name)} — Command Center · <a href="../../index.html">all projects</a></span>
<span>briefing: AI-authored at checkpoints · live state: every cycle · {_e(ledger_summary)}</span></footer>
</div></body></html>"""


def render_index(instances):
    """The state repo's landing page: every project that has a command center."""
    generated = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    cards = ""
    for inst in instances:
        b = inst.get("briefing") or {}
        pr = b.get("progress") or {}
        pct = pr.get("to_first_show_pct")
        cards += f"""
<a class="icard" href="{_e(inst["name"])}/dashboard/index.html">
  <h2>{_e(inst["name"].replace("-", " ").title())}</h2>
  <p class="desc">{_e(inst.get("description") or b.get("north_star") or "No description yet.")}</p>
  {f'<div class="bar live"><i style="width:{pct}%"></i></div><div class="bar-lbl">{pct}% to first milestone</div>' if pct is not None else ""}
  {f'<div class="pulse" style="margin-top:12px"><span class="dot"></span> {_e(b.get("live_edge"))}</div>' if b.get("live_edge") else ""}
  <div class="meta">briefing {_e(b.get("updated_at", "—")[:10])} · {inst.get("workers", 0)} tracked workers</div>
</a>"""
    if not cards:
        cards = '<div class="panel"><p class="sub">No instances found. Add projects/&lt;name&gt;/command-center/instance.json in your KB.</p></div>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Command Center</title>
<style>{CSS}</style></head><body><div class="wrap">
<header class="mast"><div>
  <p class="kicker">Fleet</p>
  <h1>Command <span class="b">Center</span></h1>
  <p class="northstar">Every large multi-session project with an orchestrator, in one place. Each card is a full program briefing — written so you can walk in cold.</p>
</div><div class="mast-meta"><div class="now">generated {generated}</div></div></header>
<div class="card-grid">{cards}</div>
<footer><span>Command Center · engine: scripts/command-center</span><span>state repo: see README's state_root setup</span></footer>
</div></body></html>"""


def load_briefing(briefing_path):
    if briefing_path and os.path.exists(briefing_path):
        try:
            with open(briefing_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
    return None


def write(state, briefing, ledger_summary, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(render(state, briefing, ledger_summary))
    return output_path


def write_index(instances, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(render_index(instances))
    return output_path


if __name__ == "__main__":
    import sys

    sys.path.insert(0, os.path.dirname(__file__))
    import reconcile

    kb_root = os.path.expanduser("~/knowledge")
    instance_path = os.path.join(kb_root, "projects", "your-project", "command-center", "instance.json")
    with open(instance_path) as f:
        instance_config = json.load(f)
    state = reconcile.build_state(kb_root, instance_config)
    out = write(state, None, "self-test run, 0 cycles logged", "/tmp/cc-dashboard-selftest/index.html")
    size = os.path.getsize(out)
    print(f"wrote {out} ({size} bytes)")
    assert size > 500
