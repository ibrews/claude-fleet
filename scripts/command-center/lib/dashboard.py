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
.haq-grid{display:grid;gap:16px;margin-top:2px}
.haq-item{border-left:3px solid var(--amber)}
.haq-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:0 0 8px}
.haq-head h3{margin:0;font-size:15px;font-weight:700;flex:1;min-width:220px;color:var(--ink)}
.haq-rank{font-family:ui-monospace,monospace;font-size:12px;color:var(--ink-faint)}
.haq-why{margin:0 0 10px;font-size:13px;color:var(--ink-dim)}
.haq-steps{margin:0 0 12px;padding-left:22px;color:var(--ink-dim);font-size:13px;display:grid;gap:6px}
.haq-cmd{margin:0;background:var(--raised);border:1px solid var(--border);border-radius:10px;padding:12px 14px;font-size:12.5px;color:var(--ink);overflow-x:auto;white-space:pre-wrap;word-break:break-word}
@media (max-width:820px){.mast{grid-template-columns:1fr}.mast-meta{text-align:left}.cols,.bigbars{grid-template-columns:1fr}.row{grid-template-columns:26px 1fr}.row>*{grid-column:2}.row .ph-n{grid-column:1}}
"""


def _e(s):
    return html.escape(str(s or ""))


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
  <div class="bigbar"><div class="t">To first live show (Phase 3)</div>
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
        phases_html = _sec("Roadmap", f'<div class="board">{rows}</div>',
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
        items = "".join(
            f'<li><span class="who">{_e(p.get("phase", "?"))}</span>'
            f'<span class="what"><b>{_e(p["title"])}</b> — {_e(p["detail"])}</span></li>'
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
{mast}{glance}{haq_html}{hint}
{recs_html}{phases_html}{topics_html}{problems_html}{timeline_html}{mech_html}{links_html}
<footer><span>{_e(name)} — Command Center · <a href="../../index.html">all projects</a></span>
<span>briefing: AI-authored at checkpoints · live state: every cycle · {_e(ledger_summary)}</span></footer>
</div>{_TZ_UPGRADE_SCRIPT}</body></html>"""


def render_index(instances):
    """The /command-center landing page: every project that has a command center."""
    generated_iso = _now_iso()
    cards = ""
    for inst in instances:
        b = inst.get("briefing") or {}
        pr = b.get("progress") or {}
        pct = pr.get("to_first_show_pct")
        briefing_ts = b.get("updated_at", "")
        briefing_when = _ts_span(briefing_ts) if briefing_ts else "—"
        cards += f"""
<a class="icard" href="{_e(inst["name"])}/dashboard/index.html">
  <button class="copylink" type="button" data-cc-name="{_e(inst["name"])}" onclick="copyCCLink(event, this)">🔗 Copy link</button>
  <h2>{_e(inst["name"].replace("-", " ").title())}</h2>
  <p class="desc">{_e(inst.get("description") or b.get("north_star") or "No description yet.")}</p>
  {f'<div class="bar live"><i style="width:{pct}%"></i></div><div class="bar-lbl">{pct}% to first-show milestone</div>' if pct is not None else ""}
  {f'<div class="pulse" style="margin-top:12px"><span class="dot"></span> {_e(b.get("live_edge"))}</div>' if b.get("live_edge") else ""}
  <div class="meta">briefing {briefing_when} · {inst.get("workers", 0)} tracked workers</div>
</a>"""
    if not cards:
        cards = '<div class="panel"><p class="sub">No instances found. Add projects/&lt;name&gt;/command-center/instance.json in the KB.</p></div>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Command Center</title>
<style>{CSS}</style></head><body><div class="wrap">
<header class="mast"><div>
  <p class="kicker">your org · Fleet</p>
  <h1>Command <span class="b">Center</span></h1>
  <p class="northstar">Every large multi-session project with an orchestrator, in one place. Each card is a full program briefing — written so you can walk in cold.</p>
</div><div class="mast-meta"><div class="now">generated {_ts_span(generated_iso)}</div></div></header>
<div class="card-grid">{cards}</div>
<footer><span>Command Center · engine: departments/engineering/command-center</span><span>state repo: your-org/command-center-state</span></footer>
</div>{_TZ_UPGRADE_SCRIPT}{_COPY_LINK_SCRIPT}</body></html>"""


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
