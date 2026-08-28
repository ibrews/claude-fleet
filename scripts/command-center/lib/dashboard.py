#!/usr/bin/env python3
"""Static dashboard generator for the Command Center — v2 (briefing edition).

Two content layers, each with its own visible staleness stamp:

  1. BRIEFING (briefing.json, AI-authored at checkpoints) — the narrative a
     cold reader needs: north star, per-phase progress, topic Q&As, unsolved
     problems, ranked recommendations, checkpoint timeline. Written for
     someone who has NOT been tracking the project.
  2. MECHANICAL (reconcile.py, regenerated every cycle) — live sessions,
     open/blocked/done triggers, anomalies, inbox items.

Visual language adapted from the operator's "Your Project — Program State" artifact
(2026-07-12): tungsten-amber + gel-teal on a dark purple-tinted ground,
monospace kickers, status pills (proven/live/blocked/planned), phase-board
rows, recommendation callout. Light + dark via prefers-color-scheme AND
data-theme overrides. Sections are collapsible (<details>) — glanceable
first, drill-down second.

Also renders the INDEX page listing every instance (for the FCC's
/command-center mount root).

If briefing.json is absent the page degrades to mechanical-only with a hint —
keeps the engine fork-clean for projects that haven't written a briefing yet.
"""
import html
import json
import os
import time
from datetime import datetime, timezone as dt_timezone
try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover — stdlib since 3.9, but degrade rather than crash a dashboard render
    _ET = None

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
.icard{border:1px solid var(--border);border-radius:14px;background:var(--surface);box-shadow:var(--shadow);padding:20px;display:block;color:inherit;text-decoration:none;position:relative}
.icard h2{margin:0 0 6px;font-size:19px;font-weight:750}
.icard .desc{font-size:13px;color:var(--ink-dim);margin:0 0 12px}
.icard .meta{font-family:ui-monospace,monospace;font-size:11px;color:var(--ink-faint);margin-top:10px}
.copylink{position:absolute;top:16px;right:16px;font-family:ui-monospace,monospace;font-size:11px;color:var(--ink-dim);padding:5px 10px;border:1px solid var(--border-soft);border-radius:8px;background:var(--surface);cursor:pointer}
.copylink:hover{color:var(--ink);border-color:var(--border)}
.work-this{display:inline-flex;align-items:center;gap:5px;margin-top:8px;border:1px solid color-mix(in srgb,var(--amber) 48%,var(--border));border-radius:7px;background:color-mix(in srgb,var(--amber) 8%,var(--surface));color:var(--amber);padding:5px 8px;font:700 10px/1 ui-monospace,"SF Mono",Menlo,monospace;letter-spacing:.06em;text-transform:uppercase;cursor:pointer}
.work-this:hover{color:var(--ink);border-color:var(--amber);background:color-mix(in srgb,var(--amber) 16%,var(--surface))}
.tour-trigger{margin-top:12px;border:1px solid color-mix(in srgb,var(--amber) 55%,var(--border));border-radius:8px;background:color-mix(in srgb,var(--amber) 10%,var(--surface));color:var(--amber);padding:8px 11px;font:700 10.5px/1 ui-monospace,"SF Mono",Menlo,monospace;letter-spacing:.08em;text-transform:uppercase;cursor:pointer}
.tour-trigger:hover{background:color-mix(in srgb,var(--amber) 17%,var(--surface));color:var(--ink)}
.tour-trigger:focus-visible,.tour button:focus-visible,.work-this:focus-visible,.work-dialog button:focus-visible,.work-dialog a:focus-visible{outline:2px solid var(--gel);outline-offset:3px}
.tour{width:min(920px,calc(100vw - 32px));max-height:min(720px,calc(100vh - 32px));padding:0;border:1px solid color-mix(in srgb,var(--amber) 42%,var(--border));border-radius:18px;background:var(--surface);color:var(--ink);box-shadow:0 32px 100px rgba(0,0,0,.62);overflow:hidden}
.tour::backdrop{background:rgba(12,9,16,.78);backdrop-filter:blur(5px)}
.tour-shell{background:linear-gradient(135deg,color-mix(in srgb,var(--amber) 4%,var(--surface)),var(--surface) 48%,color-mix(in srgb,var(--gel) 3%,var(--surface)));min-height:570px;display:flex;flex-direction:column}
.tour-head{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:18px 22px;border-bottom:1px solid var(--border);background:color-mix(in srgb,var(--ground) 38%,var(--surface))}
.tour-head h2{margin:2px 0 0;font-size:17px;letter-spacing:-.01em}
.tour-eyebrow,.tour-coordinate{margin:0;color:var(--amber);font:700 10px/1.3 ui-monospace,"SF Mono",Menlo,monospace;letter-spacing:.18em;text-transform:uppercase}
.tour-close{width:34px;height:34px;border:1px solid var(--border);border-radius:50%;background:var(--surface);color:var(--ink-dim);font-size:20px;line-height:1;cursor:pointer}
.tour-layout{display:grid;grid-template-columns:210px minmax(0,1fr);min-height:500px;flex:1}
.tour-rail{padding:20px 14px;border-right:1px solid var(--border);background:color-mix(in srgb,var(--ground) 32%,var(--surface))}
.tour-rail ol{list-style:none;margin:0;padding:0;display:grid;gap:7px}
.tour-step{position:relative;width:100%;display:grid;grid-template-columns:28px 1fr;gap:8px;align-items:center;text-align:left;border:1px solid transparent;border-radius:9px;background:transparent;color:var(--ink-faint);padding:8px;font:600 11px/1.25 ui-monospace,"SF Mono",Menlo,monospace;cursor:pointer}
.tour-step span{display:grid;place-items:center;width:26px;height:26px;border:1px solid var(--border);border-radius:7px;color:var(--ink-faint);font-size:10px}
.tour-step[aria-selected="true"]{color:var(--ink);border-color:color-mix(in srgb,var(--amber) 35%,var(--border));background:color-mix(in srgb,var(--amber) 9%,var(--surface))}
.tour-step[aria-selected="true"] span{color:var(--amber);border-color:var(--amber)}
.tour-stage{min-width:0;display:flex;flex-direction:column;padding:30px 34px 22px}
.tour-panel{margin:0;flex:1}
.tour-panel h3{margin:10px 0 14px;font-size:clamp(24px,4vw,38px);line-height:1.05;letter-spacing:-.035em;max-width:19ch}
.tour-panel>p:not(.tour-coordinate){max-width:62ch;color:var(--ink-dim);font-size:14px}
.tour-panel ul{margin:18px 0 0;padding:0;list-style:none;display:grid;gap:10px;max-width:62ch}
.tour-panel li{position:relative;padding-left:21px;color:var(--ink-dim);font-size:13px}
.tour-panel li::before{content:"";position:absolute;left:0;top:.65em;width:9px;height:1px;background:var(--amber)}
.tour-panel strong{color:var(--ink);font-weight:700}
.tour-callout{margin-top:24px;max-width:64ch;border:1px solid var(--border);border-left:3px solid var(--gel);border-radius:10px;background:color-mix(in srgb,var(--gel) 6%,var(--surface));padding:13px 15px;color:var(--ink-dim);font:11.5px/1.55 ui-monospace,"SF Mono",Menlo,monospace}
.tour-actions{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:12px;border-top:1px solid var(--border-soft);padding-top:18px;margin-top:24px}
.tour-actions button{border:1px solid var(--border);border-radius:8px;background:var(--raised);color:var(--ink);padding:9px 13px;font:700 10.5px/1 ui-monospace,"SF Mono",Menlo,monospace;letter-spacing:.06em;text-transform:uppercase;cursor:pointer}
.tour-actions button[disabled]{opacity:.35;cursor:default}
.tour-actions .tour-next{border-color:var(--amber);background:var(--amber);color:#21170a}
.tour-count{text-align:center;color:var(--ink-faint);font:10.5px/1 ui-monospace,"SF Mono",Menlo,monospace;letter-spacing:.08em;text-transform:uppercase}
.work-dialog{width:min(760px,calc(100vw - 32px));padding:0;border:1px solid color-mix(in srgb,var(--gel) 48%,var(--border));border-radius:16px;background:var(--surface);color:var(--ink);box-shadow:0 32px 100px rgba(0,0,0,.62);overflow:hidden}
.work-dialog::backdrop{background:rgba(12,9,16,.78);backdrop-filter:blur(5px)}
.work-shell{background:linear-gradient(135deg,color-mix(in srgb,var(--gel) 7%,var(--surface)),var(--surface) 58%,color-mix(in srgb,var(--amber) 4%,var(--surface)));padding:24px}
.work-head{display:flex;align-items:start;justify-content:space-between;gap:18px;padding-bottom:18px;border-bottom:1px solid var(--border)}
.work-head h2{margin:5px 0 0;font-size:clamp(21px,4vw,31px);line-height:1.08;letter-spacing:-.025em;max-width:23ch}
.work-close{width:34px;height:34px;border:1px solid var(--border);border-radius:50%;background:var(--surface);color:var(--ink-dim);font-size:20px;line-height:1;cursor:pointer}
.work-fields{margin:20px 0 0;display:grid;gap:0;border-top:1px solid var(--border-soft)}
.work-fields div{display:grid;grid-template-columns:130px minmax(0,1fr);gap:16px;padding:13px 0;border-bottom:1px solid var(--border-soft)}
.work-fields dt{color:var(--gel);font:700 10px/1.4 ui-monospace,"SF Mono",Menlo,monospace;letter-spacing:.09em;text-transform:uppercase}
.work-fields dd{margin:0;color:var(--ink-dim);font-size:13px;overflow-wrap:anywhere}
.work-fields dd strong{color:var(--ink)}
.work-note{margin:18px 0 0;border-left:3px solid var(--amber);padding:8px 0 8px 12px;color:var(--ink-faint);font:11.5px/1.5 ui-monospace,"SF Mono",Menlo,monospace}
.work-actions{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-top:20px}
.work-actions a,.work-actions button{border:1px solid var(--border);border-radius:8px;background:var(--raised);color:var(--ink);padding:10px 12px;font:700 10.5px/1 ui-monospace,"SF Mono",Menlo,monospace;letter-spacing:.06em;text-transform:uppercase;text-decoration:none;cursor:pointer}
.work-actions a{color:var(--gel);border-color:color-mix(in srgb,var(--gel) 42%,var(--border));background:color-mix(in srgb,var(--gel) 7%,var(--surface))}
.work-actions button{border-color:var(--amber);background:var(--amber);color:#21170a}
.haq-grid{display:grid;gap:16px;margin-top:2px}
.haq-item{border-left:3px solid var(--amber)}
.haq-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:0 0 8px}
.haq-head h3{margin:0;font-size:15px;font-weight:700;flex:1;min-width:220px;color:var(--ink)}
.haq-rank{font-family:ui-monospace,monospace;font-size:12px;color:var(--ink-faint)}
.haq-why{margin:0 0 10px;font-size:13px;color:var(--ink-dim)}
.haq-steps{margin:0 0 12px;padding-left:22px;color:var(--ink-dim);font-size:13px;display:grid;gap:6px}
.haq-cmd{margin:0;background:var(--raised);border:1px solid var(--border);border-radius:10px;padding:12px 14px;font-size:12.5px;color:var(--ink);overflow-x:auto;white-space:pre-wrap;word-break:break-word}
.fact-label{display:inline-flex;font-family:ui-monospace,monospace;font-size:9.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--gel);border:1px solid color-mix(in srgb,var(--gel) 30%,transparent);border-radius:5px;padding:1px 6px;margin-left:6px;vertical-align:1px}
.fact-label.ai{color:var(--amber);border-color:color-mix(in srgb,var(--amber) 36%,transparent)}
.item-detail{display:block;font-family:ui-monospace,monospace;font-size:10.5px;color:var(--ink-faint);margin-top:3px;overflow-wrap:anywhere}
.attention{border-left:3px solid var(--blocked)}
.good{border-left:3px solid var(--proven)}
.cockpit-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
@media (max-width:820px){.mast{grid-template-columns:1fr}.mast-meta{text-align:left}.cols,.bigbars{grid-template-columns:1fr}.row{grid-template-columns:26px 1fr}.row>*{grid-column:2}.row .ph-n{grid-column:1}}
@media (max-width:680px){.cockpit-grid{grid-template-columns:1fr}.card-grid{grid-template-columns:minmax(0,1fr)}.icard{min-width:0}.tour{width:calc(100vw - 12px);max-height:calc(100vh - 12px)}.tour-shell{min-height:0;max-height:calc(100vh - 14px)}.tour-layout{display:flex;flex-direction:column;min-height:0}.tour-rail{padding:10px;border-right:0;border-bottom:1px solid var(--border);overflow-x:auto}.tour-rail ol{display:flex;min-width:max-content}.tour-step{width:43px;grid-template-columns:1fr;padding:6px}.tour-step span{margin:auto}.tour-step b{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}.tour-stage{padding:24px 20px 18px;overflow-y:auto}.tour-panel h3{font-size:27px}.tour-head{padding:14px 16px}.tour-actions{position:sticky;bottom:-18px;background:var(--surface);padding:14px 0 2px}.work-dialog{width:calc(100vw - 12px)}.work-shell{padding:18px}.work-fields div{grid-template-columns:1fr;gap:5px}.work-head h2{font-size:24px}}
"""


def _e(s):
    return html.escape(str(s or ""))


def _work_this_button(project, project_href, title, evidence, next_step, done_when, verification):
    """A deliberately non-mutating handoff control for an observed risk.

    The cockpit cannot safely infer a target agent, permission scope, or
    priority from a dashboard observation. This button therefore opens a
    complete, copyable dispatch brief instead of silently creating work.
    """
    fields = {
        "project": project,
        "link": project_href,
        "title": title,
        "evidence": evidence,
        "next": next_step,
        "done": done_when,
        "verify": verification,
    }
    attrs = " ".join(f'data-work-{key}="{_e(value)}"' for key, value in fields.items())
    return f'<button class="work-this" type="button" data-work-this aria-haspopup="dialog" {attrs}>↗ Work this</button>'


_NO_UPDATE_TS = object()  # sentinel: caller didn't pass updated_iso at all -> no "Last updated" line


def _sec(title, body_html, note="", open_=True, count=None, updated_iso=_NO_UPDATE_TS):
    """A collapsible section styled like the artifact's sec-head.

    updated_iso: a REAL data timestamp for this section's content — a full
    UTC ISO datetime, a bare 'YYYY-MM-DD' date, or None (renders an honest
    "no data timestamp available"). Omit the argument entirely (the
    default sentinel) to skip the "Last updated" line altogether — used
    only by call sites with no real underlying record to point to.
    """
    n = f'<span class="note">{_e(note)}</span>' if note else ""
    u = "" if updated_iso is _NO_UPDATE_TS else _last_updated_note_html(updated_iso)
    c = f" ({count})" if count is not None else ""
    return (
        f'<details class="sec"{" open" if open_ else ""}><summary><div class="sec-head">'
        f'<h2>{_e(title)}{c}</h2><span class="rule"></span>{n}{u}<span class="tw">toggle</span>'
        f"</div></summary>{body_html}</details>"
    )


def _pill(status, label=None):
    cls = status if status in ("proven", "live", "blocked", "planned", "partial") else "planned"
    if label is None:
        label = {"live": "live edge"}.get(status, status)
    return f'<span class="pill {cls}">{_e(label)}</span>'


def _haq_badge_bucket(status):
    # Deterministic, glyph-only mapping — no keyword guessing. "▶" (ready/
    # actionable now) reads as the "proven" pill bucket (green); "⏳"/"⏸"
    # (waiting on something else) reads as the "live" pill bucket (amber,
    # matches --live's amber hue). Anything without a recognized leading
    # glyph falls back to the neutral "planned" bucket rather than guessing.
    s = (status or "").strip()
    if s.startswith("▶"):
        return "proven"
    if s.startswith("⏳") or s.startswith("⏸"):
        return "live"
    return "planned"


def _human_action_queue_html(b):
    """Render briefing.human_action_queue as a 'Waiting on you' panel.

    Degrades cleanly: absent or item-less human_action_queue renders "" so
    older briefing.json files (pre-dating this field) show nothing extra.
    """
    haq = b.get("human_action_queue") or {}
    items = haq.get("items") or []
    if not items:
        return ""
    cards = ""
    for it in sorted(items, key=lambda i: i.get("rank", 99)):
        status = it.get("status", "")
        badge = _pill(_haq_badge_bucket(status), label=status)
        steps = it.get("steps") or []
        steps_html = (
            f'<ol class="haq-steps">{"".join(f"<li>{_e(s)}</li>" for s in steps)}</ol>'
            if steps else ""
        )
        cmd = it.get("command")
        cmd_html = f'<pre class="haq-cmd mono"><code>{_e(cmd)}</code></pre>' if cmd else ""
        why = f'<p class="haq-why">{_e(it["why"])}</p>' if it.get("why") else ""
        cards += f"""
<div class="panel haq-item">
  <div class="haq-head"><span class="haq-rank">#{_e(it.get("rank", "?"))}</span><h3>{_e(it.get("title"))}</h3>{badge}</div>
  {why}{steps_html}{cmd_html}
</div>"""
    return _sec("Waiting on you", f'<div class="haq-grid">{cards}</div>',
                note=haq.get("_note", "") or "human-action queue · maintained by the orchestrator",
                open_=True, count=len(items), updated_iso=b.get("updated_at"))


def _now_iso():
    return datetime.now(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fmt_et(iso_utc):
    """Format a UTC ISO timestamp in America/New_York (your org is NYC-based)
    — correctly shows EDT or EST depending on the date, never hardcoded.
    Falls back to the raw UTC string if zoneinfo/tzdata isn't available."""
    if not _ET:
        return iso_utc.replace("T", " ").replace("Z", " UTC")
    try:
        dt = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt_timezone.utc)
        return dt.astimezone(_ET).strftime("%Y-%m-%d %-I:%M %p %Z")
    except Exception:
        return iso_utc.replace("T", " ").replace("Z", " UTC")


def _ts_span(iso_utc):
    """A <span data-utc="..."> whose text is the ET-rendered fallback — the
    inline script at the bottom of the page upgrades it to the VIEWER's own
    local time via the browser's Intl/Date API when JS runs (the ideal case:
    a NYC-based team + remote/traveling viewers each see their own clock).
    ET is the honest no-JS fallback per the operator's ask ('local, else EST — Agile
    Lens is NYC')."""
    return f'<span class="tzspan" data-utc="{_e(iso_utc)}">{_e(_fmt_et(iso_utc))}</span>'


def _fmt_last_updated(iso_utc):
    """'MM/DD/YYYY at HH:MM:SS AM/PM' in ET — the exact per-section 'Last
    updated' format the operator asked for (dashboard looked stale with no per-
    section freshness signal). Degrades to the raw ISO string rather than
    guess a timezone if zoneinfo/tzdata is unavailable."""
    try:
        dt = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ")
        if _ET:
            dt = dt.replace(tzinfo=dt_timezone.utc).astimezone(_ET)
            return dt.strftime("%m/%d/%Y at %I:%M:%S %p %Z")
        return dt.strftime("%m/%d/%Y at %I:%M:%S %p") + " UTC"
    except Exception:
        return iso_utc


def _fmt_date_only(date_str):
    """MM/DD/YYYY for a bare 'YYYY-MM-DD' record (e.g. a checkpoint entry)
    that has no time-of-day — never invent one."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%m/%d/%Y")
    except Exception:
        return date_str


def _ts_span_sec(iso_utc):
    """Like _ts_span but seconds-precision, upgraded via [data-utc-sec] —
    used only by the 'Last updated' section lines below."""
    return f'<span class="tzspan" data-utc-sec="{_e(iso_utc)}">{_e(_fmt_last_updated(iso_utc))}</span>'


def _last_updated_note_html(value):
    """Build a 'Last updated: ...' section-note fragment from a REAL data
    timestamp — never the page's render time (that would show a section as
    fresh just because someone loaded the dashboard, which is exactly the
    "looks stale/fake freshness" complaint this exists to fix).

    - Full UTC ISO datetime ('...T...Z') -> shown with time, JS-upgraded to
      the viewer's own local clock (seconds included, per the operator's ask).
    - Bare 'YYYY-MM-DD' date (e.g. a checkpoint with no recorded time) ->
      date only, no JS time upgrade — inventing a time-of-day the record
      never had would be worse than omitting one.
    - Missing/None -> an honest "no data timestamp available" rather than
      faking freshness.
    """
    if not value:
        return '<span class="note">Last updated: (no data timestamp available)</span>'
    if "T" in value:
        return f'<span class="note">Last updated: {_ts_span_sec(value)}</span>'
    return f'<span class="note">Last updated: {_e(_fmt_date_only(value))}</span>'


_COPY_LINK_SCRIPT = """<script>
function copyCCLink(evt, btn){
  evt.preventDefault(); evt.stopPropagation();
  var name = btn.getAttribute('data-cc-name');
  var url = location.origin + '/#command-center/' + name;
  var orig = btn.textContent;
  function ok(){ btn.textContent = 'Copied \\u2713'; setTimeout(function(){ btn.textContent = orig; }, 1500); }
  function fail(){ btn.textContent = 'Copy failed'; setTimeout(function(){ btn.textContent = orig; }, 1500); }
  function fallback(){
    try {
      var ta = document.createElement('textarea');
      ta.value = url; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.focus(); ta.select();
      var success = document.execCommand('copy');
      document.body.removeChild(ta);
      success ? ok() : fail();
    } catch (e) { fail(); }
  }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(url).then(ok, fallback);
  } else {
    fallback();
  }
}
</script>"""


_OPERATOR_TOUR_HTML = """
<dialog class="tour" id="cc-tour" aria-labelledby="cc-tour-title">
  <div class="tour-shell">
    <header class="tour-head">
      <div><p class="tour-eyebrow">Operations manual · 3 minute circuit</p><h2 id="cc-tour-title">Cockpit walkthrough</h2></div>
      <button class="tour-close" type="button" data-tour-close aria-label="Close walkthrough">×</button>
    </header>
    <div class="tour-layout">
      <nav class="tour-rail" aria-label="Walkthrough checkpoints"><ol>
        <li><button class="tour-step" type="button" data-tour-step="0" aria-selected="true"><span>01</span><b>Orient</b></button></li>
        <li><button class="tour-step" type="button" data-tour-step="1" aria-selected="false"><span>02</span><b>Trust</b></button></li>
        <li><button class="tour-step" type="button" data-tour-step="2" aria-selected="false"><span>03</span><b>Decide</b></button></li>
        <li><button class="tour-step" type="button" data-tour-step="3" aria-selected="false"><span>04</span><b>De-risk</b></button></li>
        <li><button class="tour-step" type="button" data-tour-step="4" aria-selected="false"><span>05</span><b>Verify</b></button></li>
        <li><button class="tour-step" type="button" data-tour-step="5" aria-selected="false"><span>06</span><b>Operate</b></button></li>
      </ol></nav>
      <div class="tour-stage">
        <section class="tour-panel" data-tour-panel="0" tabindex="-1">
          <p class="tour-coordinate">01 / Orient</p><h3>This is lean delivery control, not Scrum theater.</h3>
          <p>The top strip is your thirty-second scan across every visible project. It counts live work, human gates, blocked tickets, CI failures, unintegrated Git work, telemetry gaps, and ticket-contract problems.</p>
          <div class="tour-callout">Start here. A non-zero number is a reason to inspect—not automatic proof that the project is unhealthy.</div>
        </section>
        <section class="tour-panel" data-tour-panel="1" tabindex="-1" hidden>
          <p class="tour-coordinate">02 / Trust</p><h3>Know which statements are facts.</h3>
          <p><strong>Machine fact</strong> labels mean the value was deterministically collected from tickets, sessions, Git, CI, or host reports. <strong>AI summary</strong> labels mean an agent wrote the interpretation at a checkpoint.</p>
          <ul><li>Every fact has a source or freshness timestamp.</li><li>Missing and stale evidence stays visible; it is never converted into a green state.</li><li>Project briefings can lag reality, so their own update time is shown separately.</li></ul>
        </section>
        <section class="tour-panel" data-tour-panel="2" tabindex="-1" hidden>
          <p class="tour-coordinate">03 / Decide</p><h3>“Needs the operator” is the human decision queue.</h3>
          <p>This panel should contain genuine approvals, choices, credentials, or external gates—not routine agent work. Each item shows its owner, what it is blocked on, and when it should be checked again.</p>
          <div class="tour-callout">Your job: decide, delegate, or reject. If an agent could safely resolve it, the item does not belong in this queue.</div>
        </section>
        <section class="tour-panel" data-tour-panel="3" tabindex="-1" hidden>
          <p class="tour-coordinate">04 / De-risk</p><h3>Delivery risks show where work can fall off the table.</h3>
          <ul><li><strong>Red CI</strong> is the latest configured workflow result.</li><li><strong>Blocked</strong> means a ticket cannot advance without a named condition.</li><li><strong>Git</strong> exposes dirty checkouts and branches not integrated into the default branch.</li><li><strong>Stale report / host gap</strong> means the collector cannot prove the remote checkout state.</li></ul>
          <div class="tour-callout">Use <strong>Work this</strong> beside a risk to open a complete dispatch brief. It copies the evidence and a suggested definition of done, but does not silently create a ticket or start an agent.</div>
        </section>
        <section class="tour-panel" data-tour-panel="4" tabindex="-1" hidden>
          <p class="tour-coordinate">05 / Verify</p><h3>A ticket closes only with evidence.</h3>
          <p>The durable queue lives in <strong>triggers/*.md</strong>. A current ticket names its project, one owner, an observable definition of done, and the exact verification to run. Review and completed tickets link the resulting evidence.</p>
          <ul><li>Open a project card for the full delivery evidence and briefing.</li><li>Use “Recently completed” to confirm the result and evidence survived archival.</li><li>Ticket integrity calls out incomplete contracts instead of silently accepting them.</li></ul>
        </section>
        <section class="tour-panel" data-tour-panel="5" tabindex="-1" hidden>
          <p class="tour-coordinate">06 / Operate</p><h3>Run the same short loop every day.</h3>
          <ul><li>Check the generated time and evidence freshness.</li><li>Clear genuine human gates in “Needs the operator.”</li><li>Triage red CI, blockers, Git drift, and host gaps.</li><li>Open the affected project card and inspect the source evidence.</li><li>Close work only after verification, evidence, integration, and deployment are recorded.</li></ul>
          <div class="tour-callout">That loop is the project-management system: a Kanban-style flow with explicit ownership, proof, and escalation. A full Scrum ceremony is optional—not a prerequisite for control.</div>
        </section>
        <footer class="tour-actions">
          <button type="button" data-tour-back disabled>Back</button>
          <span class="tour-count" data-tour-count aria-live="polite">Step 1 of 6</span>
          <button class="tour-next" type="button" data-tour-next>Next checkpoint</button>
        </footer>
      </div>
    </div>
  </div>
</dialog>"""


_OPERATOR_TOUR_SCRIPT = """<script>
(function(){
  var dialog = document.getElementById('cc-tour');
  if (!dialog) return;
  var panels = dialog.querySelectorAll('[data-tour-panel]');
  var steps = dialog.querySelectorAll('[data-tour-step]');
  var back = dialog.querySelector('[data-tour-back]');
  var next = dialog.querySelector('[data-tour-next]');
  var count = dialog.querySelector('[data-tour-count]');
  var current = 0, lastFocus = null;

  function show(index, focusPanel){
    current = Math.max(0, Math.min(panels.length - 1, index));
    for (var i = 0; i < panels.length; i++) {
      var active = i === current;
      panels[i].hidden = !active;
      steps[i].setAttribute('aria-selected', active ? 'true' : 'false');
      steps[i].tabIndex = active ? 0 : -1;
    }
    back.disabled = current === 0;
    next.textContent = current === panels.length - 1 ? 'Finish tour' : 'Next checkpoint';
    count.textContent = 'Step ' + (current + 1) + ' of ' + panels.length;
    if (focusPanel) panels[current].focus();
  }
  function openTour(opener){
    lastFocus = opener || document.activeElement;
    show(0, false);
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
    panels[0].focus();
  }
  function closeTour(){
    if (typeof dialog.close === 'function') dialog.close();
    else { dialog.removeAttribute('open'); restoreFocus(); }
  }
  function restoreFocus(){ if (lastFocus && lastFocus.focus) lastFocus.focus(); }

  var openers = document.querySelectorAll('[data-tour-open]');
  for (var i = 0; i < openers.length; i++) {
    openers[i].addEventListener('click', function(){ openTour(this); });
  }
  for (var j = 0; j < steps.length; j++) {
    steps[j].addEventListener('click', function(){ show(Number(this.getAttribute('data-tour-step')), true); });
  }
  dialog.querySelector('[data-tour-close]').addEventListener('click', closeTour);
  back.addEventListener('click', function(){ show(current - 1, true); });
  next.addEventListener('click', function(){
    if (current === panels.length - 1) closeTour();
    else show(current + 1, true);
  });
  dialog.addEventListener('close', restoreFocus);
  dialog.addEventListener('keydown', function(evt){
    if (evt.key === 'ArrowRight') { evt.preventDefault(); show(current + 1, true); }
    if (evt.key === 'ArrowLeft') { evt.preventDefault(); show(current - 1, true); }
  });
})();
</script>"""


_WORK_THIS_HTML = """
<dialog class="work-dialog" id="cc-work-this" aria-labelledby="cc-work-title">
  <div class="work-shell">
    <header class="work-head">
      <div><p class="tour-eyebrow">Dispatch brief · no work created yet</p><h2 id="cc-work-title" data-work-title>Turn this observation into work</h2></div>
      <button class="work-close" type="button" data-work-close aria-label="Close dispatch brief">×</button>
    </header>
    <dl class="work-fields">
      <div><dt>Project</dt><dd data-work-project></dd></div>
      <div><dt>Starting evidence</dt><dd data-work-evidence></dd></div>
      <div><dt>Recommended first move</dt><dd data-work-next></dd></div>
      <div><dt>Done when</dt><dd data-work-done></dd></div>
      <div><dt>Verify by</dt><dd data-work-verify></dd></div>
    </dl>
    <p class="work-note">Review the evidence first. Copying this brief does not dispatch an agent, change a ticket, or alter the project.</p>
    <footer class="work-actions">
      <a data-work-open href="#">Open project evidence ↗</a>
      <button type="button" data-work-copy>Copy dispatch brief</button>
    </footer>
  </div>
</dialog>"""


_WORK_THIS_SCRIPT = """<script>
(function(){
  var dialog = document.getElementById('cc-work-this');
  if (!dialog) return;
  var fields = ['project', 'title', 'evidence', 'next', 'done', 'verify', 'link'];
  var lastFocus = null, brief = '';
  function value(btn, key){ return btn.getAttribute('data-work-' + key) || ''; }
  function assign(key, text){
    var target = dialog.querySelector('[data-work-' + key + ']');
    if (target) target.textContent = text;
  }
  function close(){
    if (typeof dialog.close === 'function') dialog.close();
    else { dialog.removeAttribute('open'); restoreFocus(); }
  }
  function restoreFocus(){ if (lastFocus && lastFocus.focus) lastFocus.focus(); }
  function copied(button){
    var original = button.textContent;
    button.textContent = 'Copied ✓';
    setTimeout(function(){ button.textContent = original; }, 1500);
  }
  function copyBrief(button){
    function fallback(){
      try {
        var area = document.createElement('textarea');
        area.value = brief; area.style.position = 'fixed'; area.style.opacity = '0';
        document.body.appendChild(area); area.focus(); area.select();
        var ok = document.execCommand('copy'); document.body.removeChild(area);
        if (ok) copied(button);
      } catch (e) {}
    }
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(brief).then(function(){ copied(button); }, fallback);
    else fallback();
  }
  var controls = document.querySelectorAll('[data-work-this]');
  for (var i = 0; i < controls.length; i++) {
    controls[i].addEventListener('click', function(){
      lastFocus = this;
      var values = {};
      for (var j = 0; j < fields.length; j++) values[fields[j]] = value(this, fields[j]);
      assign('title', values.title); assign('project', values.project); assign('evidence', values.evidence);
      assign('next', values.next); assign('done', values.done); assign('verify', values.verify);
      var link = dialog.querySelector('[data-work-open]');
      link.setAttribute('href', values.link);
      brief = 'Dispatch brief\\nWork: ' + values.title + '\\nProject: ' + values.project +
        '\\nStarting evidence: ' + values.evidence + '\\nRecommended first move: ' + values.next +
        '\\nDone when: ' + values.done + '\\nVerify by: ' + values.verify + '\\nProject evidence: ' + values.link;
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open', '');
      dialog.querySelector('[data-work-copy]').focus();
    });
  }
  dialog.querySelector('[data-work-close]').addEventListener('click', close);
  dialog.querySelector('[data-work-copy]').addEventListener('click', function(){ copyBrief(this); });
  dialog.addEventListener('close', restoreFocus);
})();
</script>"""


_TZ_UPGRADE_SCRIPT = """<script>
(function(){
  function upgrade(attr, opts){
    var els = document.querySelectorAll('[' + attr + ']');
    for (var i = 0; i < els.length; i++) {
      var el = els[i], iso = el.getAttribute(attr);
      try {
        var d = new Date(iso);
        if (isNaN(d.getTime())) continue;
        el.textContent = d.toLocaleString(undefined, opts);
      } catch (e) {}
    }
  }
  upgrade('data-utc', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: 'numeric', minute: '2-digit', timeZoneName: 'short'
  });
  // Seconds-precision variant for the per-section "Last updated" lines.
  upgrade('data-utc-sec', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: 'numeric', minute: '2-digit', second: '2-digit', timeZoneName: 'short'
  });
})();
</script>"""


def _briefing_age_days(briefing):
    try:
        t = time.strptime(briefing["updated_at"][:10], "%Y-%m-%d")
        return int((time.time() - time.mktime(t)) / 86400)
    except Exception:
        return None


def _machine_cockpit_html(state):
    """Machine-derived delivery facts: tickets, Git integration, and CI."""
    quality = state.get("work_item_quality") or {}
    needs = state.get("needs_human") or []
    delivery_state = state.get("delivery") or {}
    delivery_summary = state.get("delivery_summary") or {}
    repos = delivery_state.get("repositories") or []

    needs_items = "".join(
        f'<li><span class="who">{_e(t.get("priority", "normal"))}</span>'
        f'<span class="what"><b>{_e(t.get("title") or t.get("id"))}</b>'
        f'<span class="item-detail">owner: {_e(t.get("owner") or "unassigned")} · '
        f'blocked on: {_e(t.get("blocked_on") or t.get("acceptance") or "human gate")} · '
        f'next check: {_e(t.get("next_check") or "not set")} · {_e(t.get("file"))}</span></span></li>'
        for t in needs
    ) or '<li><span class="what">nothing currently requires the operator</span></li>'

    ci_items = ""
    integration_items = ""
    for repo in repos:
        ci = repo.get("ci") or {}
        ci_status = ci.get("status", "unavailable")
        ci_bucket = {"green": "proven", "running": "live", "red": "blocked"}.get(ci_status, "planned")
        red_links = " ".join(
            f'<a href="{_e(run.get("url"))}" target="_blank">{_e(run.get("workflowName") or "workflow")} ↗</a>'
            for run in ci.get("red", []) if run.get("url")
        )
        ci_items += (
            f'<li><span class="who">{_e(repo.get("github") or repo.get("name"))}</span>'
            f'<span class="what"><b>CI {_pill(ci_bucket, ci_status)}</b>'
            f'<span class="item-detail">{_e(ci.get("source") or "GitHub Actions")} · '
            f'{len(ci.get("workflows", []))} latest workflow result(s)'
            f'{(" · " + red_links) if red_links else ""}'
            f'{(" · " + _e(ci.get("error"))) if ci.get("error") else ""}</span></span></li>'
        )
        if repo.get("telemetry_status") == "stale":
            integration_items += (
                f'<li><span class="who">stale report</span><span class="what"><b>{_e(repo.get("name"))}</b> '
                f'is showing an old {_e(repo.get("evidence_host") or "remote host")} snapshot'
                f'<span class="item-detail">age: {_e(repo.get("report_age_minutes"))}m · '
                f'{_e(repo.get("telemetry_error") or repo.get("source"))}</span></span></li>'
            )
        if not repo.get("available"):
            integration_items += (
                f'<li><span class="who">unavailable</span><span class="what"><b>{_e(repo.get("name"))}</b> '
                f'local Git telemetry is unavailable on this host'
                f'<span class="item-detail">{_e(repo.get("path"))} · '
                f'{_e(repo.get("telemetry_error") or repo.get("error") or "checkout unavailable")} · '
                f'{_e(repo.get("source"))}</span></span></li>'
            )
            continue
        if repo.get("dirty"):
            integration_items += (
                f'<li><span class="who">dirty</span><span class="what"><b>{_e(repo.get("name"))}</b> '
                f'has {repo.get("dirty_entries", 0)} uncommitted entrie(s)'
                f'<span class="item-detail">{_e(repo.get("path"))} · {_e(repo.get("source"))}</span></span></li>'
            )
        for branch in repo.get("unintegrated_branches", []):
            integration_items += (
                f'<li><span class="who">{"stale · " if branch.get("stale") else ""}{branch.get("unique_commits", 0)} commit(s)</span>'
                f'<span class="what"><b>{_e(branch.get("branch"))}</b> is not integrated into the local default-branch snapshot'
                f'<span class="item-detail">{_e(repo.get("name"))} · upstream: '
                f'{_e(branch.get("upstream") or "none")} · last commit: {_e(branch.get("committed_at"))}'
                f'{(" · " + _e(branch.get("age_days")) + "d old") if branch.get("age_days") is not None else ""}</span></span></li>'
            )
    if not ci_items:
        ci_items = '<li><span class="what">repository delivery tracking is not enabled for this project</span></li>'
    if not integration_items:
        integration_items = '<li><span class="what">no dirty checkout or unintegrated local branch detected</span></li>'

    integrity_issues = (quality.get("issues") or []) + (quality.get("closure_issues") or [])
    issue_items = "".join(
        f'<li><span class="who">{_e(issue.get("severity"))}</span>'
        f'<span class="what"><b>{_e(issue.get("id"))}</b> — {_e(issue.get("message"))}'
        f'<span class="item-detail">{_e(issue.get("file"))}</span></span></li>'
        for issue in integrity_issues[:12]
    ) or '<li><span class="what">all active tickets satisfy the current contract</span></li>'

    stats = f"""
<div class="stat-strip">
  <span><b>{quality.get('active_count', 0)}</b> active tickets</span>
  <span><b>{quality.get('error_count', 0)}</b> ticket errors</span>
  <span><b>{quality.get('migration_issue_count', 0)}</b> migration warnings</span>
  <span><b>{quality.get('verified_closure_count', 0)}</b> verified v1 closures</span>
  <span><b>{quality.get('closure_error_count', 0)}</b> closure errors</span>
  <span><b>{len(needs)}</b> need the operator</span>
  <span><b>{delivery_summary.get('red_ci', 0)}</b> red CI</span>
  <span><b>{delivery_summary.get('local_unavailable', 0)}</b> local checks unavailable</span>
  <span><b>{delivery_summary.get('stale_reports', 0)}</b> stale host reports</span>
  <span><b>{delivery_summary.get('dirty_repos', 0)}</b> dirty repos</span>
  <span><b>{delivery_summary.get('unintegrated_branches', 0)}</b> unintegrated branches</span>
</div>"""
    body = f"""{stats}<div class="cockpit-grid" style="margin-top:16px">
  <div class="panel{' attention' if needs else ''}"><h3>Needs the operator <span class="fact-label">machine fact</span></h3><p class="sub">explicit human gates and approval waits</p><ul class="clean">{needs_items}</ul></div>
  <div class="panel{' attention' if delivery_summary.get('red_ci') else ''}"><h3>Verification &amp; CI <span class="fact-label">machine fact</span></h3><p class="sub">latest result per configured workflow</p><ul class="clean">{ci_items}</ul></div>
  <div class="panel{' attention' if delivery_summary.get('dirty_repos') or delivery_summary.get('unintegrated_branches') or delivery_summary.get('local_unavailable') or delivery_summary.get('stale_reports') else ' good'}"><h3>Unintegrated work <span class="fact-label">machine fact</span></h3><p class="sub">host Git snapshots; stale or unavailable evidence is explicit, never treated as clean</p><ul class="clean">{integration_items}</ul></div>
  <div class="panel{' attention' if quality.get('error_count') or quality.get('closure_error_count') else ''}"><h3>Ticket integrity <span class="fact-label">machine fact</span></h3><p class="sub">owner · definition of done · verification · blocker follow-up · closure proof</p><ul class="clean">{issue_items}</ul></div>
</div>"""
    return _sec("Delivery cockpit", body,
                note="operational facts · every claim links to a ticket, Git state, or CI run",
                open_=True, updated_iso=state.get("generated_at"))


def render(state, briefing, ledger_summary):
    generated_iso = _now_iso()
    b = briefing or {}
    name = state["instance"]

    # ---- masthead ----
    title_html = _e(name.replace("-", " ").title())
    parts = title_html.rsplit(" ", 1)
    if len(parts) == 2:
        title_html = f'{parts[0]} <span class="b">{parts[1]}</span>'
    age = _briefing_age_days(b)
    stale_chip = f'<span class="stale">briefing {age}d old — may lag reality</span>' if (age is not None and age > 3) else ""
    briefing_ts = b.get("updated_at", "")
    briefing_when = _ts_span(briefing_ts) if briefing_ts else _e(briefing_ts)
    mast = f"""
<header class="mast"><div>
  <p class="kicker">Command Center · Program Briefing</p>
  <h1>{title_html}</h1>
  {f'<p class="northstar">{_e(b.get("north_star"))}</p>' if b.get("north_star") else ""}
</div><div class="mast-meta">
  <div class="now">live state {_ts_span(generated_iso)}</div>
  {f'<div>briefing as of {briefing_when}{stale_chip}</div>' if b else '<div>no briefing yet — mechanical view only</div>'}
  {f'<div class="pulse"><span class="dot"></span> live edge: {_e(b.get("live_edge"))}</div>' if b.get("live_edge") else ""}
</div></header>"""

    # ---- glance: one-liner + big progress bars ----
    glance = ""
    if b.get("one_liner_now"):
        glance += f'<p class="northstar" style="max-width:none;margin-top:20px"><b>Where we are:</b> {_e(b["one_liner_now"])}</p>'
        glance += (f'<p style="margin:4px 0 0;font-family:ui-monospace,monospace;'
                   f'font-size:11px;color:var(--ink-faint)">{_last_updated_note_html(b.get("updated_at"))}</p>')
    pr = b.get("progress") or {}
    if pr:
        glance += f"""
<div class="bigbars">
  <div class="bigbar"><div class="t">{_e(pr.get("to_first_show_label", "To first live show (Phase 3)"))}</div>
    <div class="n">{pr.get("to_first_show_pct", 0)}<small>%</small></div>
    <div class="bar live"><i style="width:{pr.get("to_first_show_pct", 0)}%"></i></div>
    <div class="why">{_e(pr.get("to_first_show_note"))}</div></div>
  <div class="bigbar"><div class="t">Full roadmap</div>
    <div class="n">{pr.get("full_roadmap_pct", 0)}<small>%</small></div>
    <div class="bar planned"><i style="width:{pr.get("full_roadmap_pct", 0)}%;background:var(--gel)"></i></div>
    <div class="why">{_e(pr.get("full_roadmap_note"))}</div></div>
</div>"""
        # Staleness backstop: the phase board is copied from the roadmap doc's
        # ```phases block and these bigbars are COMPUTED from those phase pcts each
        # cycle — so their honest freshness is the ROADMAP's own updated date (not
        # the narrative's updated_at, not render time), and they can't sit stale
        # while the phases move.
        if b.get("phases_updated"):
            glance += (f'<p style="margin:8px 0 0;font-family:ui-monospace,monospace;font-size:11px;'
                       f'color:var(--ink-faint)">phase board synced from the roadmap doc · bigbars auto-computed '
                       f'from phase progress · roadmap updated {_e(_fmt_date_only(b["phases_updated"]))}</p>')

    # ---- waiting on you (human action queue) ----
    haq_html = _human_action_queue_html(b)
    machine_cockpit_html = _machine_cockpit_html(state)

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
                         note="ranked · AI project manager's call, argue with it",
                         updated_iso=b.get("updated_at"))

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
        phases_updated = b.get("phases_updated")
        # Deterministic, suggestion-only sanity checks (status/pct inconsistencies +
        # staleness) computed fresh each cycle. Surfaced, never auto-applied — the
        # numbers stay human-authored; this just flags "a human should look."
        nudges = state.get("phase_nudges") or []
        nudge_html = ""
        if nudges:
            lis = "".join(f"<li>{_e(n['message'])}</li>" for n in nudges)
            nudge_html = (
                '<div class="panel" style="margin-top:14px;border-left:3px solid var(--amber)">'
                '<p class="sub" style="margin:0 0 8px">⚠ consistency checks — suggestions only, '
                'nothing is auto-applied; edit the roadmap block if one looks right</p>'
                '<ul style="margin:0;padding-left:20px;display:grid;gap:6px;font-size:13px;'
                f'color:var(--ink-dim)">{lis}</ul></div>'
            )
        phases_html = _sec("Roadmap", f'<div class="board">{rows}</div>{nudge_html}',
                           note=("phases · status · progress — synced from the roadmap doc"
                                 if phases_updated else "phases · status · progress · current state"),
                           updated_iso=phases_updated or b.get("updated_at"))

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
                           count=len(b["topics"]), updated_iso=b.get("updated_at"))

    # ---- problems ----
    problems_html = ""
    if b.get("problems"):
        import time as _time
        _today = _time.strftime("%Y-%m-%d", _time.gmtime())

        def _ladder_badge(p):
            # Escalation-ladder fields on open problems (2026-07-23): the ladder
            # only works if owner/date/flag-count are VISIBLE, not buried in JSON.
            if p.get("phase") != "open":
                return ""
            bits = [f'owner: {_e(p.get("owner", "unassigned"))}']
            nc = p.get("next_check")
            if nc:
                overdue = nc < _today
                bits.append(f'next check: {_e(nc)}' + (' ⚠ OVERDUE' if overdue else ''))
            fc = p.get("flag_count", 1)
            bits.append(f'flagged ×{fc}' + (' ⚠' if fc >= 3 else ''))
            return f'<br><small style="opacity:.75">{" · ".join(bits)}</small>'

        items = "".join(
            f'<li><span class="who">{_e(p.get("phase", "?"))}</span>'
            f'<span class="what"><b>{_e(p["title"])}</b> — {_e(p["detail"])}{_ladder_badge(p)}</span></li>'
            for p in b["problems"]
        )
        problems_html = _sec("Biggest unsolved problems",
                             f'<div class="panel"><ul class="clean">{items}</ul></div>',
                             count=len(b["problems"]), updated_iso=b.get("updated_at"))

    # ---- checkpoint timeline ----
    timeline_html = ""
    if b.get("checkpoints"):
        items = "".join(
            f'<li><span class="d">{_e(c["date"])}</span><span class="k"></span><span class="w">{_e(c["label"])}</span></li>'
            for c in reversed(b["checkpoints"])
        )
        # Most recent checkpoint's own date — more granular than the whole-
        # briefing updated_at, and it's real per-entry data already on hand.
        latest_cp_date = max(
            (c.get("date", "") for c in b["checkpoints"] if c.get("date")), default=None
        )
        timeline_html = _sec("Checkpoint timeline",
                             f'<div class="panel"><ul class="tl">{items}</ul></div>',
                             note="newest first", open_=False, updated_iso=latest_cp_date)

    # ---- mechanical layer ----
    tw = state.get("tracked_workers", [])
    # Maps reconcile.py's per-worker status to a pill CSS bucket. "live" (an
    # ACTUAL matched, pid-alive, non-stale session) is the only status that may
    # ever render the "live" bucket — this is the fix for the bug where
    # "trigger open" (just an open ticket, no live session) was mapped to the
    # "live" bucket and rendered as a misleading "LIVE EDGE" badge on workers
    # that were not, in fact, running. Because "live" here comes from the same
    # sessions_live list the headline counter is built from, a worker can only
    # ever show live-bucket styling when the counter is non-zero — counter and
    # roster can no longer contradict each other.
    status_pill = {"live": "live", "blocked": "blocked", "trigger open": "partial", "no current activity": "planned"}
    # Human-readable label is the worker's REAL reconciled status text, not the
    # CSS bucket name — so "trigger open" reads as "ticket open" (honest: a
    # ticket exists, nobody is live on it) rather than inheriting "live edge"
    # from whatever bucket it happens to share styling with.
    status_label = {"live": "live edge", "blocked": "blocked", "trigger open": "ticket open", "no current activity": "idle"}
    tw_items = "".join(
        f'<li><span class="who">{_e(w["repo"])}</span><span class="what"><b>{_e(w["name"])}</b> — {_e(w["note"])} '
        f'{_pill(status_pill.get(w["status"], "planned"), label=status_label.get(w["status"], w["status"]))}</span></li>'
        for w in tw
    )
    anomalies = [s for s in state["sessions_stale_or_dead"] if s.get("claim")]
    live_sessions = state.get("sessions_live", [])
    orch_active = state.get("orchestrator_dispatched_active", [])

    def _live_who(s):
        # The master orchestrator session gets a distinct amber "who" chip
        # instead of blending in as just another machine name — surfacing it
        # explicitly in the live view, per the accuracy-bug fix.
        if not s.get("is_master"):
            return f'<span class="who">{_e(s["machine"])}</span>'
        style = ("color:var(--amber);border-color:color-mix(in srgb,var(--amber) 30%,transparent);"
                 "background:color-mix(in srgb,var(--amber) 12%,transparent)")
        return f'<span class="who" style="{style}">★ master</span>'

    live_items = "".join(
        f'<li>{_live_who(s)}<span class="what">{_e(s["doing"] or s["slug"])}</span></li>'
        for s in live_sessions
    )
    live_items += "".join(
        f'<li><span class="who">↳ dispatched</span><span class="what">{_e(t["title"] or t["id"])} '
        f'<span class="mono" style="color:var(--ink-faint)">({_e(t.get("claimed_by"))})</span></span></li>'
        for t in orch_active
    )
    mech_body = f"""
<div class="stat-strip">
  <span><b>{len(state["triggers_in_flight"])}</b> in flight</span>
  <span><b>{len(state["triggers_blocked"])}</b> blocked</span>
  <span><b>{len(state["triggers_done"])}</b> done recently</span>
  <span><b>{len(live_sessions)}</b> live sessions</span>
  <span><b>{len(orch_active)}</b> orchestrator-dispatched</span>
  <span><b>{len(anomalies)}</b> anomalies</span>
  <span><b>{len(state["inbox_open"])}</b> open inbox items</span>
</div>
<div class="cols" style="margin-top:16px">
  <div class="panel"><h3>Live now</h3><p class="sub">real sessions (pid-alive + fresh heartbeat) · master starred · + orchestrator-dispatched work</p>
    <ul class="clean">{live_items or '<li><span class="what">no live sessions</span></li>'}</ul></div>
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
                     note=f"mechanical · regenerated every cycle · {ledger_summary}", open_=False,
                     updated_iso=generated_iso)

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
{mast}{glance}{machine_cockpit_html}{haq_html}{hint}
{recs_html}{phases_html}{topics_html}{problems_html}{timeline_html}{mech_html}{links_html}
<footer><span>{_e(name)} — Command Center · <a href="../../index.html">all projects</a></span>
<span>briefing: AI-authored at checkpoints · live state: every cycle · {_e(ledger_summary)}</span></footer>
</div>{_TZ_UPGRADE_SCRIPT}</body></html>"""


def render_index(instances):
    """Fleet-wide delivery cockpit plus the per-project briefing cards."""
    generated_iso = _now_iso()
    live_seen = set()
    active_work = []
    needs_by_ticket = {}
    blocked_by_ticket = {}
    red_ci = []
    unintegrated = []
    local_unavailable = []
    stale_reports = []
    done_by_ticket = {}
    ticket_issue_keys = set()

    for inst in instances:
        state = inst.get("state") or {}
        for session in state.get("sessions_live", []):
            key = (session.get("machine"), session.get("slug"))
            if key in live_seen:
                continue
            live_seen.add(key)
            active_work.append((inst, session))
        for item in state.get("needs_human", []):
            needs_by_ticket.setdefault(item.get("file") or item.get("id"), (inst, item))
        for item in state.get("triggers_blocked", []):
            blocked_by_ticket.setdefault(item.get("file") or item.get("id"), (inst, item))
        for item in state.get("triggers_done", []):
            done_by_ticket.setdefault(item.get("file") or item.get("id"), (inst, item))
        for issue in (state.get("work_item_quality") or {}).get("issues", []):
            ticket_issue_keys.add((
                issue.get("file"), issue.get("field"), issue.get("message"), issue.get("severity")
            ))
        for repo in (inst.get("delivery") or {}).get("repositories", []):
            if (repo.get("ci") or {}).get("status") == "red":
                red_ci.append((inst, repo))
            if repo.get("dirty") or repo.get("unintegrated_branches"):
                unintegrated.append((inst, repo))
            if not repo.get("available"):
                local_unavailable.append((inst, repo))
            if repo.get("telemetry_status") == "stale":
                stale_reports.append((inst, repo))

    needs_human = list(needs_by_ticket.values())
    blocked = list(blocked_by_ticket.values())
    recently_done = sorted(
        done_by_ticket.values(),
        key=lambda pair: pair[1].get("completed_at") or "",
        reverse=True,
    )
    ticket_errors = sum(key[3] == "error" for key in ticket_issue_keys)
    migration_warnings = sum(key[3] == "warning" for key in ticket_issue_keys)

    def project_link(inst):
        return f'{_e(inst["name"])}/dashboard/index.html'

    needs_html = "".join(
        f'<li><span class="who">{_e(inst["name"])}</span><span class="what">'
        f'<a href="{project_link(inst)}"><b>{_e(item.get("title") or item.get("id"))}</b></a>'
        f'<span class="item-detail">owner: {_e(item.get("owner") or "unassigned")} · '
        f'blocked on: {_e(item.get("blocked_on") or item.get("acceptance") or "human gate")} · '
        f'next check: {_e(item.get("next_check") or "not set")}</span></span></li>'
        for inst, item in needs_human[:12]
    ) or '<li><span class="what">nothing currently requires the operator</span></li>'

    active_html = "".join(
        f'<li><span class="who">{_e(session.get("machine"))}</span><span class="what">'
        f'<a href="{project_link(inst)}"><b>{_e(inst["name"])}</b></a> — '
        f'{_e(session.get("doing") or session.get("slug"))}'
        f'<span class="item-detail">heartbeat age: {_e(session.get("heartbeat_age_min"))}m · '
        f'status: {_e(session.get("status"))}</span></span></li>'
        for inst, session in active_work[:16]
    ) or '<li><span class="what">no fresh, pid-alive project sessions</span></li>'

    risk_rows = ""
    for inst, repo in red_ci:
        repo_name = repo.get("github") or repo.get("name") or "configured repository"
        failures = len((repo.get("ci") or {}).get("red", []))
        work = _work_this_button(
            inst["name"], project_link(inst), f"Investigate red CI in {repo_name}",
            f"{failures} latest configured workflow result(s) failing for {repo_name}.",
            "Open the project evidence, identify the newest failed workflow, and reproduce or diagnose before changing the release path.",
            "The latest configured workflow passes, or the failure is documented with an owner, concrete blocker, and dated next check.",
            "Link the workflow result and the relevant test output or diagnostic evidence to the ticket.",
        )
        risk_rows += (
            f'<li><span class="who">red CI</span><span class="what"><a href="{project_link(inst)}">'
            f'<b>{_e(inst["name"])}</b></a> — {_e(repo_name)}'
            f'<span class="item-detail">{failures} failing latest workflow result(s)</span>{work}</span></li>'
        )
    for inst, item in blocked[:8]:
        item_title = item.get("title") or item.get("id") or "blocked ticket"
        blocked_on = item.get("blocked_on") or "unblock condition missing"
        work = _work_this_button(
            inst["name"], project_link(inst), f"Unblock {item_title}",
            f"Current block: {blocked_on}",
            "Decide whether the named condition needs a human decision or can be resolved safely by an agent, then assign the next move.",
            "The ticket returns to in-progress with a concrete next action, or it records the exact human decision and a dated next check.",
            "Update the ticket’s status, blocker, owner, and verification evidence in the durable queue.",
        )
        risk_rows += (
            f'<li><span class="who">blocked</span><span class="what"><a href="{project_link(inst)}">'
            f'<b>{_e(inst["name"])}</b></a> — {_e(item_title)}'
            f'<span class="item-detail">{_e(blocked_on)}</span>{work}</span></li>'
        )
    for inst, repo in unintegrated[:8]:
        details = []
        if repo.get("dirty"):
            details.append(f'{repo.get("dirty_entries", 0)} uncommitted entries')
        if repo.get("unintegrated_branches"):
            details.append(f'{len(repo["unintegrated_branches"])} unintegrated branches')
        detail_text = " · ".join(details)
        repo_name = repo.get("name") or repo.get("github") or "configured repository"
        work = _work_this_button(
            inst["name"], project_link(inst), f"Reconcile Git work in {repo_name}",
            f"{detail_text or 'Git integration risk'} · source: {repo.get('source') or 'repository evidence'}.",
            "Inspect the checkout and outstanding branches; preserve the work, then decide whether to integrate it or record its owner and next action.",
            "The checkout is clean and branches are integrated, or each remaining item has an explicit owner, purpose, and next check.",
            "Record git status plus merge-base or pull-request evidence; never discard unreviewed work to make the dashboard green.",
        )
        risk_rows += (
            f'<li><span class="who">Git</span><span class="what"><a href="{project_link(inst)}">'
            f'<b>{_e(inst["name"])}</b></a> — {_e(repo_name)}'
            f'<span class="item-detail">{_e(detail_text)} · {_e(repo.get("source"))}</span>{work}</span></li>'
        )
    for inst, repo in stale_reports[:8]:
        repo_name = repo.get("name") or repo.get("github") or "configured repository"
        evidence_host = repo.get("evidence_host") or "remote host"
        report_age = repo.get("report_age_minutes")
        work = _work_this_button(
            inst["name"], project_link(inst), f"Restore fresh host evidence for {repo_name}",
            f"{evidence_host} report is {report_age}m old: {repo.get('telemetry_error') or repo.get('source') or 'no fresh report'}.",
            "Check the reporter on the assigned host and publish a new read-only snapshot before judging the checkout’s delivery state.",
            "The cockpit has a fresh host report or an explicit, owned infrastructure blocker with a next check.",
            "Confirm report timestamp, repository path, and source in the project evidence panel.",
        )
        risk_rows += (
            f'<li><span class="who">stale report</span><span class="what"><a href="{project_link(inst)}">'
            f'<b>{_e(inst["name"])}</b></a> — {_e(repo_name)}'
            f'<span class="item-detail">{_e(evidence_host)} · '
            f'{_e(report_age)}m old · '
            f'{_e(repo.get("telemetry_error") or repo.get("source"))}</span>{work}</span></li>'
        )
    for inst, repo in local_unavailable[:8]:
        repo_name = repo.get("name") or repo.get("github") or "configured repository"
        telemetry_error = repo.get("telemetry_error") or repo.get("error") or "local checkout unavailable on collector host"
        work = _work_this_button(
            inst["name"], project_link(inst), f"Restore delivery evidence for {repo_name}",
            f"Checkout path: {repo.get('path') or 'not recorded'} · {telemetry_error}",
            "Confirm which host owns the checkout, then restore the configured path or enable its read-only host reporter.",
            "The cockpit receives fresh repository evidence, or the project records a named owner and dated infrastructure blocker.",
            "Confirm the configured host/path and a fresh report in the project evidence panel.",
        )
        risk_rows += (
            f'<li><span class="who">host gap</span><span class="what"><a href="{project_link(inst)}">'
            f'<b>{_e(inst["name"])}</b></a> — {_e(repo_name)}'
            f'<span class="item-detail">{_e(repo.get("path"))} · '
            f'{_e(telemetry_error)}</span>{work}</span></li>'
        )
    risk_rows = risk_rows or '<li><span class="what">no configured delivery risk detected</span></li>'

    done_html = "".join(
        f'<li><span class="who">{_e(inst["name"])}</span><span class="what">'
        f'<a href="{project_link(inst)}"><b>{_e(item.get("title") or item.get("id"))}</b></a>'
        f'<span class="item-detail">completed: {_e(item.get("completed_at") or "date not recorded")} · '
        f'evidence: {_e(item.get("evidence") or "not linked")}</span></span></li>'
        for inst, item in recently_done[:12]
    ) or '<li><span class="what">no completed tickets matched current project instances</span></li>'

    cockpit = f"""
<div class="stat-strip">
  <span><b>{len(instances)}</b> visible projects</span>
  <span><b>{len(active_work)}</b> live sessions</span>
  <span><b>{len(needs_human)}</b> need the operator</span>
  <span><b>{len(blocked)}</b> blocked tickets</span>
  <span><b>{len(red_ci)}</b> repos with red CI</span>
  <span><b>{len(unintegrated)}</b> repos with unintegrated work</span>
  <span><b>{len(local_unavailable)}</b> local checks unavailable</span>
  <span><b>{len(stale_reports)}</b> stale host reports</span>
  <span><b>{ticket_errors}</b> ticket errors</span>
  <span><b>{migration_warnings}</b> migration warnings</span>
</div>
<div class="cockpit-grid" style="margin-top:20px">
  <div class="panel{' attention' if needs_human else ''}"><h3>Needs the operator <span class="fact-label">machine fact</span></h3><p class="sub">decisions and human gates only</p><ul class="clean">{needs_html}</ul></div>
  <div class="panel"><h3>Live operations <span class="fact-label">machine fact</span></h3><p class="sub">fresh heartbeat + live process; duplicate sessions collapsed</p><ul class="clean">{active_html}</ul></div>
  <div class="panel{' attention' if red_ci or blocked or unintegrated or local_unavailable or stale_reports else ' good'}"><h3>Delivery risks <span class="fact-label">machine fact</span></h3><p class="sub">red CI · blocked tickets · Git risks · stale or unavailable telemetry</p><ul class="clean">{risk_rows}</ul></div>
  <div class="panel"><h3>Recently completed <span class="fact-label">machine fact</span></h3><p class="sub">ticket result; missing evidence is shown, never implied</p><ul class="clean">{done_html}</ul></div>
</div>"""

    cards = ""
    for inst in instances:
        b = inst.get("briefing") or {}
        state = inst.get("state") or {}
        delivery_summary = state.get("delivery_summary") or {}
        need_count = len(state.get("needs_human", []))
        blocked_count = len(state.get("triggers_blocked", []))
        live_count = len(state.get("sessions_live", []))
        issue_count = (state.get("work_item_quality") or {}).get("error_count", 0)
        attention = (
            need_count + blocked_count + delivery_summary.get("red_ci", 0)
            + delivery_summary.get("local_unavailable", 0)
            + delivery_summary.get("stale_reports", 0)
            + (state.get("work_item_quality") or {}).get("closure_error_count", 0)
        )
        if attention:
            health = _pill("blocked", "attention")
        elif live_count:
            health = _pill("live", "active")
        else:
            health = _pill("planned", "quiet")
        pr = b.get("progress") or {}
        pct = pr.get("to_first_show_pct")
        briefing_ts = b.get("updated_at", "")
        briefing_when = _ts_span(briefing_ts) if briefing_ts else "—"
        cards += f"""
<a class="icard" href="{_e(inst["name"])}/dashboard/index.html">
  <button class="copylink" type="button" data-cc-name="{_e(inst["name"])}" onclick="copyCCLink(event, this)">🔗 Copy link</button>
  <h2>{_e(inst["name"].replace("-", " ").title())} {health}</h2>
  <p class="desc">{_e(inst.get("description") or b.get("north_star") or "No description yet.")}</p>
  {f'<div class="bar live"><i style="width:{pct}%"></i></div><div class="bar-lbl">{pct}% to first-show milestone</div>' if pct is not None else ""}
  {f'<div class="pulse" style="margin-top:12px"><span class="dot"></span> {_e(b.get("live_edge"))}</div>' if b.get("live_edge") else ""}
  <div class="stat-strip"><span><b>{live_count}</b> live</span><span><b>{need_count}</b> need the operator</span><span><b>{blocked_count}</b> blocked</span><span><b>{delivery_summary.get('red_ci', 0)}</b> red CI</span><span><b>{delivery_summary.get('local_unavailable', 0)}</b> host gaps</span><span><b>{delivery_summary.get('stale_reports', 0)}</b> stale reports</span><span><b>{issue_count}</b> ticket errors</span></div>
  <div class="meta">briefing {briefing_when} <span class="fact-label ai">AI summary</span> · operational state {_ts_span(generated_iso)} <span class="fact-label">machine fact</span></div>
</a>"""
    if not cards:
        cards = '<div class="panel"><p class="sub">No instances found. Add projects/&lt;name&gt;/command-center/instance.json in the KB.</p></div>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Command Center</title>
<style>{CSS}</style></head><body><div class="wrap">
<header class="mast"><div>
  <p class="kicker">your org · Fleet</p>
  <h1>Delivery <span class="b">Cockpit</span></h1>
  <p class="northstar">Goals, live sessions, tickets, blockers, Git integration, and CI in one place. Machine facts are labeled separately from AI-authored project briefings.</p>
</div><div class="mast-meta"><div class="now">generated {_ts_span(generated_iso)}</div>
<button class="tour-trigger" type="button" data-tour-open aria-haspopup="dialog">↗ Run 3-minute tour</button></div></header>
{cockpit}
<div class="sec-head" style="margin-top:34px"><h2>Project briefings</h2><span class="rule"></span><span class="note">open a card for evidence and full context</span></div>
<div class="card-grid">{cards}</div>
<footer><span>Command Center · engine: departments/engineering/command-center</span><span>state repo: your-org/command-center-state</span></footer>
</div>{_OPERATOR_TOUR_HTML}{_WORK_THIS_HTML}{_TZ_UPGRADE_SCRIPT}{_COPY_LINK_SCRIPT}{_OPERATOR_TOUR_SCRIPT}{_WORK_THIS_SCRIPT}</body></html>"""


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
