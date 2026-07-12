#!/usr/bin/env python3
"""Static dashboard generator for the Command Center.

Reads the state model (from reconcile.py) and the ledger (from ledger.py)
and renders one self-contained index.html — no build step, no external
CSS/JS, dark-mode aware via prefers-color-scheme. This is the persistent,
hosted replacement for the one-off "Persona Live — Program State" artifact.

Hosting note: this writes a file to disk. Actually publishing it on GitHub
Pages requires a repo (private, per the 2026-07-12 design decision) with
Pages enabled — creating a new repo is a real, confirmable action, not
something to do silently as part of generating HTML. Until that repo
exists, this generates locally; the file is real and correct either way.
"""
import html
import os
import time

CSS = """
:root { --bg:#0b0c0f; --card:#15171c; --text:#e8e8ea; --muted:#8b8d94;
        --green:#3ba55d; --amber:#d99a2b; --red:#d9534f; --border:#2a2c33; }
@media (prefers-color-scheme: light) {
  :root { --bg:#f7f7f8; --card:#ffffff; --text:#1a1a1e; --muted:#5a5c63;
          --green:#1d9e75; --amber:#ba7517; --red:#a32d2d; --border:#e2e2e6; }
}
* { box-sizing: border-box; }
body { margin:0; padding:32px; background:var(--bg); color:var(--text);
       font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
h1 { font-size:20px; margin:0 0 4px; }
.meta { color:var(--muted); font-size:12px; margin-bottom:28px; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:16px; margin-bottom:28px; }
.card { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:16px; }
.card h2 { font-size:13px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); margin:0 0 12px; }
.row { padding:8px 0; border-top:1px solid var(--border); font-size:13px; }
.row:first-child { border-top:none; }
.tag { display:inline-block; font-size:11px; padding:1px 7px; border-radius:99px; margin-right:6px; }
.tag.done { background:color-mix(in srgb, var(--green) 20%, transparent); color:var(--green); }
.tag.blocked { background:color-mix(in srgb, var(--red) 20%, transparent); color:var(--red); }
.tag.progress { background:color-mix(in srgb, var(--amber) 20%, transparent); color:var(--amber); }
.tag.idle { background:color-mix(in srgb, var(--muted) 20%, transparent); color:var(--muted); }
.empty { color:var(--muted); font-style:italic; font-size:12px; }
.footer { color:var(--muted); font-size:11px; margin-top:24px; }
.wide { grid-column: 1 / -1; }
"""


def _row(text, tag_cls=None, tag_text=None):
    tag = f'<span class="tag {tag_cls}">{html.escape(tag_text)}</span>' if tag_cls else ""
    return f'<div class="row">{tag}{html.escape(text)}</div>'


def _card(title, rows):
    body = "".join(rows) if rows else '<div class="empty">nothing here right now</div>'
    return f'<div class="card"><h2>{html.escape(title)}</h2>{body}</div>'


def render(state, ledger_summary):
    generated = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

    in_flight_rows = [
        _row(t["title"] or t["id"], "progress", t.get("claimed_by") or t.get("target") or "unclaimed")
        for t in state["triggers_in_flight"]
    ]
    blocked_rows = [
        _row(t["title"] or t["id"], "blocked", t.get("target", ""))
        for t in state["triggers_blocked"]
    ]
    done_rows = [
        _row(t["title"] or t["id"], "done", t.get("claimed_by") or "")
        for t in state["triggers_done"]
    ]
    sessions_rows = [
        _row(f'{s["machine"]}: {s["doing"]}', None, None) for s in state["sessions_live"]
    ]
    anomaly_rows = [
        _row(
            f'{s["machine"]}/{s["slug"]}: claim "{s["claim"]}" — '
            f'{"process gone" if not s["pid_alive"] else "stale heartbeat"} '
            f'({s["heartbeat_age_min"]}m ago)',
            "blocked", "anomaly",
        )
        for s in state["sessions_stale_or_dead"] if s.get("claim")
    ]
    inbox_rows = [_row(i["line"].lstrip("- [ ] ").lstrip("*")) for i in state["inbox_open"][:10]]

    status_tag = {"live": "done", "blocked": "blocked", "trigger open": "progress", "no current activity": "idle"}
    tracked_rows = [
        _row(f'{w["name"]} ({w["repo"]}) — {w["note"]}', status_tag[w["status"]], w["status"])
        for w in state.get("tracked_workers", [])
    ]

    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(state["instance"])} — Command Center</title>
<style>{CSS}</style></head><body>
<h1>{html.escape(state["instance"])} — Program State</h1>
<div class="meta">Generated {generated} · {ledger_summary}</div>
<div class="grid">
{_card(f"Tracked workers ({len(state.get('tracked_workers', []))})", tracked_rows) if state.get("tracked_workers") else ""}
{_card(f"In flight ({len(state['triggers_in_flight'])})", in_flight_rows)}
{_card(f"Blocked ({len(state['triggers_blocked'])})", blocked_rows)}
{_card(f"Done recently ({len(state['triggers_done'])})", done_rows)}
{_card(f"Live sessions ({len(state['sessions_live'])})", sessions_rows)}
{_card(f"Anomalies — abandoned/stale claims ({len(anomaly_rows)})", anomaly_rows)}
{_card(f"Open inbox items ({len(state['inbox_open'])})", inbox_rows)}
</div>
<div class="footer">Command Center orchestrator · composes session-board + triggers + inbox, no data duplicated —
this is a read-only view generated fresh each cycle.</div>
</body></html>"""


def write(state, ledger_summary, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    html_out = render(state, ledger_summary)
    with open(output_path, "w") as f:
        f.write(html_out)
    return output_path


if __name__ == "__main__":
    import json
    import sys

    sys.path.insert(0, os.path.dirname(__file__))
    import reconcile

    kb_root = os.path.expanduser("~/knowledge")
    instance_path = os.path.join(kb_root, "projects", "your-project", "command-center", "instance.json")
    with open(instance_path) as f:
        instance_config = json.load(f)
    state = reconcile.build_state(kb_root, instance_config)
    out = write(state, "self-test run, 0 cycles logged", "/tmp/cc-dashboard-selftest/index.html")
    size = os.path.getsize(out)
    print(f"wrote {out} ({size} bytes)")
    assert size > 500
