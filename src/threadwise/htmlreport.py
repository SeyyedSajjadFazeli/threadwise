"""A self-contained HTML report: no CDN, no external images, prints to PDF.

Every number in here comes from the Report object.  Nothing is illustrative,
because a benchmark report that invents numbers is worse than no report.
"""

from __future__ import annotations

import html
import json
from typing import Iterable

from .bench import Report
from .insight import batching_advice, cost_model, decision, human_time, practical_gain
from .sweep import Sweep

CSS = """
:root{
  --bg:#0b0f17; --panel:#121826; --panel2:#171f30; --line:#243044;
  --ink:#e8eef8; --muted:#8b9bb4; --dim:#5d6b82;
  --green:#37d399; --amber:#f2b455; --red:#f0656f; --blue:#4da3ff; --violet:#a78bfa;
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink)}
body{font:15px/1.6 ui-sans-serif,-apple-system,"Segoe UI",Inter,Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;padding:48px 24px 80px}
.wrap{max-width:1060px;margin:0 auto}
.top{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;
  border-bottom:1px solid var(--line);padding-bottom:26px;margin-bottom:34px}
.brand{font:600 12px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.22em;
  text-transform:uppercase;color:var(--dim)}
h1{font-size:30px;line-height:1.2;margin:10px 0 8px;letter-spacing:-.02em;font-weight:650}
.sub{color:var(--muted);font-size:14px;max-width:62ch}
.meta{text-align:right;font:12px/1.9 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--dim);white-space:nowrap}
.decision{background:linear-gradient(135deg,#101a17,#0f1626);border:1px solid #1f3a31;
  border-left:4px solid var(--green);border-radius:14px;padding:26px 28px;margin-bottom:30px}
.decision.warn{border-color:#3a3222;border-left-color:var(--amber);
  background:linear-gradient(135deg,#1a1710,#0f1626)}
.decision h2{margin:0 0 6px;font-size:23px;letter-spacing:-.01em;display:flex;gap:12px;align-items:baseline;flex-wrap:wrap}
.decision p{margin:0;color:#c3cfdf;font-size:15px}
.pill{font:11px/1 ui-monospace,monospace;letter-spacing:.1em;text-transform:uppercase;
  padding:5px 9px;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin:26px 0 32px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px}
.stat .k{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--dim);margin-bottom:8px}
.stat .v{font:600 25px/1.1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:-.02em}
.stat .n{font-size:12px;color:var(--muted);margin-top:6px}
.stat.good .v{color:var(--green)} .stat.bad .v{color:var(--red)} .stat.mid .v{color:var(--amber)}
section{margin:40px 0}
h3{font-size:13px;letter-spacing:.16em;text-transform:uppercase;color:var(--dim);
  font-weight:600;margin:0 0 16px;padding-bottom:10px;border-bottom:1px solid var(--line)}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:right;padding:11px 12px;border-bottom:1px solid #1b2434}
th:first-child,td:first-child{text-align:left}
th{font:11px/1 ui-monospace,monospace;letter-spacing:.12em;text-transform:uppercase;color:var(--dim)}
td.num{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
tr.best td{background:#101a17}
tr.best td:first-child{box-shadow:inset 3px 0 0 var(--green)}
.tag{font:10px/1 ui-monospace,monospace;letter-spacing:.1em;text-transform:uppercase;color:var(--green);
  border:1px solid #24503f;padding:3px 6px;border-radius:5px;margin-left:8px}
.na{color:var(--dim)}
.bar{height:9px;border-radius:3px;background:#1b2434;position:relative;min-width:80px;overflow:hidden}
.bar>i{position:absolute;inset:0 auto 0 0;border-radius:3px;background:var(--blue)}
.bar>i.g{background:var(--green)} .bar>i.a{background:var(--amber)} .bar>i.r{background:var(--red)}
.note{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:14px 16px;
  margin:10px 0;font-size:14px;color:#c8d4e4;display:flex;gap:12px}
.note b{color:var(--ink);font-weight:600}
.note .dot{flex:0 0 auto;width:7px;height:7px;border-radius:50%;background:var(--amber);margin-top:8px}
.note.ok .dot{background:var(--green)} .note.err .dot{background:var(--red)}
svg{display:block;width:100%;height:auto;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:8px}
.legend{display:flex;gap:20px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-top:10px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:22px}
@media (max-width:820px){.two{grid-template-columns:1fr}.meta{display:none}}
footer{margin-top:56px;padding-top:20px;border-top:1px solid var(--line);color:var(--dim);
  font:11px/1.7 ui-monospace,monospace}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.92em;
  background:#161e2c;border:1px solid var(--line);border-radius:5px;padding:2px 6px}
@media print{body{background:#fff;color:#111;padding:0}
  .stat,.decision,svg,.note{break-inside:avoid} .top{border-color:#ddd}}
"""


def _esc(s: object) -> str:
    return html.escape(str(s))


def _bar_cell(frac: float, colour: str) -> str:
    width = max(0.0, min(1.0, frac)) * 100
    return f'<div class="bar"><i class="{colour}" style="width:{width:.1f}%"></i></div>'


def _speedup_colour(sp: float) -> str:
    if sp != sp:
        return "b"
    if sp >= 2.0:
        return "g"
    if sp >= 1.15:
        return "a"
    if sp < 0.9:
        return "r"
    return "b"


def _results_table(r: Report) -> str:
    rows = []
    max_sp = max((r.speedup(x) for x in r.results if not x.error), default=1.0)
    max_sp = max(1.0, max_sp)
    for res in r.results:
        if res.error:
            rows.append(
                f"<tr><td>{_esc(res.mode)}</td><td class='num na'>n/a</td>"
                f"<td class='num na'>—</td><td class='num na'>—</td>"
                f"<td class='na'>{_esc(res.error)}</td></tr>"
            )
            continue
        sp = r.speedup(res)
        eff = r.efficiency(res)
        is_best = (not r.suppressed) and res.mode == r.best_mode and sp >= 1.15
        cls = " class='best'" if is_best else ""
        tag = "<span class='tag'>recommended</span>" if is_best else ""
        eff_txt = "—" if res.mode == "serial" else f"{eff * 100:.0f}%"
        rows.append(
            f"<tr{cls}><td>{_esc(res.mode)}{tag}</td>"
            f"<td class='num'>{human_time(res.median)}</td>"
            f"<td class='num'>{human_time(res.median / r.tasks)}</td>"
            f"<td class='num'>{sp:.2f}×</td>"
            f"<td class='num'>{eff_txt}</td>"
            f"<td>{_bar_cell(sp / max_sp, _speedup_colour(sp))}</td></tr>"
        )
    return (
        "<table><thead><tr><th>mode</th><th>wall time</th><th>per task</th>"
        "<th>speedup</th><th>efficiency</th><th></th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _svg_seconds(r: Report) -> str:
    """Horizontal bars in log-ish scale: linear would let serial flatten the rest."""
    items = [(x, r.speedup(x)) for x in r.results if not x.error]
    if not items:
        return ""
    base = r.baseline_s or max(x.median for x, _ in items)
    w, rowh, pad_l, pad_r = 720, 40, 110, 90
    h = len(items) * rowh + 24
    rows = []
    for i, (res, sp) in enumerate(items):
        y = 12 + i * rowh
        frac = (res.median / base) if base else 1.0
        length = max(2.0, frac * (w - pad_l - pad_r))
        col = {"g": "#37d399", "a": "#f2b455", "r": "#f0656f", "b": "#4da3ff"}[
            _speedup_colour(sp)
        ]
        label = f"{sp:.2f}×" if res.mode != "serial" else "baseline"
        rows.append(
            f"<text x='{pad_l - 14}' y='{y + 15}' text-anchor='end' fill='#8b9bb4' "
            f"font-size='13' font-family='ui-monospace,monospace'>{_esc(res.mode)}</text>"
            f"<rect x='{pad_l}' y='{y}' width='{length:.1f}' height='{rowh - 14}' rx='4' fill='{col}'/>"
            f"<text x='{pad_l + length + 10}' y='{y + 16}' fill='#c3cfdf' font-size='12.5' "
            f"font-family='ui-monospace,monospace'>{human_time(res.median)} · {label}</text>"
        )
    return (
        f"<svg viewBox='0 0 {w} {h}' role='img' aria-label='wall time by mode'>"
        + "".join(rows)
        + "</svg>"
    )


def _svg_sweep(s: Sweep) -> str:
    if len(s.points) < 2:
        return ""
    w, h = 720, 300
    pad_l, pad_r, pad_t, pad_b = 56, 20, 22, 42
    xs = [p.workers for p in s.points]
    ys = [p.speedup for p in s.points]
    x_max = max(xs)
    import math

    y_max = max(max(ys) * 1.25, 2.0)
    if s.fit and not s.fit.is_lower_bound and math.isfinite(s.fit.max_speedup):
        y_max = max(y_max, min(s.fit.max_speedup * 1.1, max(ys) * 3))

    def px(n: float) -> float:
        return pad_l + (n - 1) / max(1, x_max - 1) * (w - pad_l - pad_r)

    def py(v: float) -> float:
        return h - pad_b - v / y_max * (h - pad_t - pad_b)

    grid = []
    step = 1 if y_max <= 6 else 2 if y_max <= 20 else 5
    v = 0
    while v <= y_max:
        grid.append(
            f"<line x1='{pad_l}' y1='{py(v):.1f}' x2='{w - pad_r}' y2='{py(v):.1f}' "
            f"stroke='#1b2434' stroke-width='1'/>"
            f"<text x='{pad_l - 10}' y='{py(v) + 4:.1f}' text-anchor='end' fill='#5d6b82' "
            f"font-size='11' font-family='ui-monospace,monospace'>{v}×</text>"
        )
        v += step
    for n in xs:
        grid.append(
            f"<text x='{px(n):.1f}' y='{h - pad_b + 20}' text-anchor='middle' fill='#5d6b82' "
            f"font-size='11' font-family='ui-monospace,monospace'>{n}</text>"
        )
    grid.append(
        f"<text x='{(pad_l + w - pad_r) / 2:.0f}' y='{h - 6}' text-anchor='middle' "
        f"fill='#5d6b82' font-size='11' font-family='ui-monospace,monospace'>workers</text>"
    )

    pts = " ".join(f"{px(n):.1f},{py(v):.1f}" for n, v in zip(xs, ys))
    ideal = " ".join(f"{px(n):.1f},{py(min(n, y_max)):.1f}" for n in xs)

    fit_path = ""
    if s.fit:
        fit_path = (
            f"<polyline points='"
            + " ".join(
                f"{px(i):.1f},{py(min(1 / (s.fit.serial_fraction + (1 - s.fit.serial_fraction) / i), y_max)):.1f}"
                for i in range(1, x_max + 1)
            )
            + f"' fill='none' stroke='#a78bfa' stroke-width='1.5' stroke-dasharray='5 5' opacity='.85'/>"
        )

    dots = "".join(
        f"<circle cx='{px(n):.1f}' cy='{py(v):.1f}' r='4.5' fill='#37d399' "
        f"stroke='#0b0f17' stroke-width='2'/>"
        for n, v in zip(xs, ys)
    )
    ceiling = ""
    if (
        s.fit
        and not s.fit.is_lower_bound
        and math.isfinite(s.fit.max_speedup)
        and s.fit.max_speedup <= y_max
    ):
        yc = py(s.fit.max_speedup)
        ceiling = (
            f"<line x1='{pad_l}' y1='{yc:.1f}' x2='{w - pad_r}' y2='{yc:.1f}' "
            f"stroke='#f2b455' stroke-width='1' stroke-dasharray='2 4'/>"
            f"<text x='{w - pad_r - 4}' y='{yc - 6:.1f}' text-anchor='end' fill='#f2b455' "
            f"font-size='11' font-family='ui-monospace,monospace'>ceiling "
            f"{s.fit.max_speedup:.1f}×</text>"
        )

    return (
        f"<svg viewBox='0 0 {w} {h}' role='img' aria-label='speedup versus workers'>"
        + "".join(grid)
        + f"<polyline points='{ideal}' fill='none' stroke='#2b3a52' stroke-width='1.5' "
        f"stroke-dasharray='3 3'/>"
        + fit_path
        + ceiling
        + f"<polyline points='{pts}' fill='none' stroke='#37d399' stroke-width='2.5'/>"
        + dots
        + "</svg>"
        + "<div class='legend'>"
        "<span><i style='background:#37d399'></i>measured</span>"
        "<span><i style='background:#2b3a52'></i>perfect scaling</span>"
        "<span><i style='background:#a78bfa'></i>Amdahl fit</span>"
        + ("<span><i style='background:#f2b455'></i>predicted ceiling</span>" if ceiling else "")
        + "</div>"
    )


def _notes(r: Report) -> str:
    out = []
    if r.consistent:
        out.append("<div class='note ok'><span class='dot'></span><div>"
                   "<b>Every mode returned the same result</b> — checksums match, so the "
                   "comparison is between schedules, not between different answers.</div></div>")
    else:
        out.append("<div class='note err'><span class='dot'></span><div>"
                   "<b>The modes disagree.</b> Timings below are meaningless until the outputs "
                   "match; treat this as a correctness bug, not a performance result.</div></div>")
    for n in r.notes:
        cls = "note err" if "WARNING" in n else ("note" if "only" in n else "note ok")
        out.append(
            f"<div class='{cls}'><span class='dot'></span><div>{_esc(n)}</div></div>"
        )
    extra = batching_advice(r)
    if extra:
        out.append(f"<div class='note'><span class='dot'></span><div><b>Batching:</b> {_esc(extra)}</div></div>")
    return "".join(out)


def render_body(
    report: Report | None = None,
    sweep: Sweep | None = None,
    title: str = "threadwise report",
    show_header: bool = True,
) -> str:
    """The page content without <html>/<head>/<body>, so it can be embedded."""
    if report is None and sweep is None:
        raise ValueError("need a report or a sweep")
    w = report.workload if report else sweep.workload  # type: ignore[union-attr]
    mode, reason = decision(report) if report else ("Scalability sweep", "")
    warn = report.suppressed if report else (sweep.cpu_usable < 1.5 and w.kind == "cpu")

    stats = []
    if report:
        best = report._best_result()
        sp = report.speedup(best) if best else 1.0
        stats.append(("recommended", best.mode if best and not report.suppressed else "—",
                      "measuring the machine" if report.suppressed else "fastest mode measured",
                      "good" if sp >= 1.15 and not report.suppressed else "mid"))
        stats.append(("speedup", f"{sp:.2f}×", "vs running serially",
                      "good" if sp >= 1.15 else "mid"))
        stats.append(("wall time", human_time(best.median) if best else "—",
                      practical_gain(report) or f"serial {human_time(report.baseline_s)}", ""))
        stats.append(("identical results", "yes" if report.consistent else "no",
                      "checksums across all modes", "good" if report.consistent else "bad"))
        stats.append(("usable cpu", f"{report.cpu.usable:g}" if report.cpu else f"{report.workers}",
                      f"{report.cpu.logical} visible, {report.workers} used" if report.cpu
                      else f"{report.workers} workers", "mid" if report.suppressed else ""))
    if sweep and sweep.fit:
        stats.append(("serial fraction", f"{sweep.fit.serial_fraction * 100:.1f}%",
                      f"fit quality R² {sweep.fit.r2:.2f}",
                      "good" if sweep.fit.serial_fraction < 0.02 else "mid"))
        if sweep.fit.max_speedup == float("inf"):
            stats.append(("ceiling", "none found", "no bend within the measured range", ""))
        elif sweep.fit.is_lower_bound:
            stats.append(("ceiling", f"≥ {sweep.fit.max_speedup:.0f}×",
                          "curve had not bent when the sweep stopped", "mid"))
        else:
            stats.append(("ceiling", f"{sweep.fit.max_speedup:.1f}×",
                          "no worker count beats this", ""))
    stat_html = "".join(
        f"<div class='stat {cls}'><div class='k'>{_esc(k)}</div><div class='v'>{_esc(v)}</div>"
        f"<div class='n'>{_esc(n)}</div></div>"
        for k, v, n, cls in stats
    )

    sections = []
    if report:
        model = cost_model(report)
        sections.append(
            "<section><h3>execution modes</h3>" + _results_table(report) + "</section>"
        )
        sections.append(
            "<section><h3>wall time by mode</h3>" + _svg_seconds(report) + "</section>"
        )
        detail = [
            f"<b>job:</b> {report.tasks} independent tasks × "
            f"{human_time(report.baseline_s / report.tasks)} serial each",
            f"<b>harness:</b> {report.repeat} timed repeats, {report.warmup} warmup, median reported",
            f"<b>platform:</b> Python {report.python} on {report.platform}",
        ]
        if model and model.per_task_overhead_s > 1e-6:
            detail.append(
                f"<b>process overhead:</b> {human_time(model.per_task_overhead_s)} per task "
                f"(break-even at {model.break_even_workers:.1f} workers)"
            )
        sections.append(
            "<section><h3>how this was measured</h3>"
            + "".join(f"<div class='note'><span class='dot'></span><div>{d}</div></div>" for d in detail)
            + "</section>"
        )
    if sweep:
        sections.append(
            f"<section><h3>scalability · {_esc(sweep.mode)} mode · {sweep.tasks} tasks</h3>"
            + _svg_sweep(sweep)
            + "</section>"
        )
        if sweep.fit:
            sections.append(
                "<section><h3>what the curve means</h3>"
                + "".join(
                    f"<div class='note'><span class='dot'></span><div>{_esc(n)}</div></div>"
                    for n in sweep.notes
                )
                + "</section>"
            )
    if report:
        sections.append("<section><h3>why</h3>" + _notes(report) + "</section>")

    payload = {}
    if report:
        payload["report"] = report.to_dict()
    if sweep:
        payload["sweep"] = sweep.to_dict()

    header = ""
    if show_header:
        header = (
            '<div class="top"><div>'
            '<div class="brand">threadwise · concurrency report</div>'
            f"<h1>{_esc(w.name)}</h1>"
            f'<div class="sub">{_esc(w.description)}</div></div>'
            f'<div class="meta">{_esc(w.kind)}-bound<br>{_esc(title)}<br>threadwise 1.1</div></div>'
        )
    else:
        header = (
            f'<div class="brand" style="margin-bottom:8px">{_esc(w.name)} · '
            f'{_esc(w.kind)}</div>'
            f'<div class="sub" style="margin-bottom:18px">{_esc(w.description)}</div>'
        )
    return (
        header
        + f'<div class="decision{" warn" if warn else ""}">'
        + f"<h2>{_esc(mode)}"
        + ('<span class="pill">insufficient cpu</span>' if warn else "")
        + f"</h2><p>{_esc(reason)}</p></div>"
        + f'<div class="grid">{stat_html}</div>'
        + "".join(sections)
        + "<footer>generated by threadwise · every figure on this page came from a run on this "
        "machine · raw data embedded below<br>"
        "<code>python -m json.tool &lt; report.json</code></footer>"
        + f'<script type="application/json" class="threadwise-data">{json.dumps(payload)}</script>'
    )


def render_html(
    report: Report | None = None,
    sweep: Sweep | None = None,
    title: str = "threadwise report",
) -> str:
    body = render_body(report=report, sweep=sweep, title=title)
    return (
        "<!doctype html>\n<html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{_esc(title)}</title><style>{CSS}</style></head>"
        f"<body><div class='wrap'>{body}</div></body></html>"
    )


def render_multi(reports: list[Report], title: str = "threadwise · all workloads") -> str:
    """Several workloads in one page, so `bench --all --html` is not a silent lie."""
    if not reports:
        raise ValueError("no reports")
    if len(reports) == 1:
        return render_html(report=reports[0], title=title)
    blocks = []
    nav = []
    for i, r in enumerate(reports):
        mode, reason = decision(r)
        sp = r.best_speedup
        nav.append(
            f"<a class='wlink' href='#w{i}'><b>{_esc(r.workload.name)}</b>"
            f"<span>{_esc(r.workload.kind)} · {sp:.2f}× → {_esc(mode)}</span></a>"
        )
        blocks.append(
            f"<div id='w{i}' style='margin-top:42px'>"
            f"<h2 style='font-size:22px;margin:0 0 4px'>{_esc(r.workload.name)}</h2>"
            f"<p style='color:var(--dim);margin:0 0 16px;font-size:13px'>"
            f"{_esc(r.workload.description)}</p>"
            + render_body(report=r, title=title, show_header=False)
            + "</div>"
        )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{_esc(title)}</title><style>{CSS}"
        ".wlink{display:flex;justify-content:space-between;gap:16px;padding:12px 16px;"
        "border:1px solid var(--line);border-radius:9px;margin-bottom:8px;"
        "background:var(--panel);font-size:14px;text-decoration:none;color:var(--ink)}"
        ".wlink span{color:var(--muted);font-family:ui-monospace,monospace;font-size:12px}"
        ".wlink:hover{border-color:#2f4b6b}</style></head><body><div class='wrap'>"
        "<div class='brand' style='font:600 12px/1 ui-monospace,monospace;letter-spacing:.2em;"
        "text-transform:uppercase;color:var(--dim);margin-bottom:14px'>threadwise · all workloads</div>"
        f"<h1 style='font-size:28px;margin:0 0 20px'>{len(reports)} workloads, one run each</h1>"
        + "".join(nav)
        + "".join(blocks)
        + "</div></body></html>"
    )


def write_html(path: str, report: Report | None = None, sweep: Sweep | None = None,
               title: str = "threadwise report", reports: list[Report] | None = None) -> str:
    if reports:
        content = render_multi(reports, title=title)
    else:
        content = render_html(report=report, sweep=sweep, title=title)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path
