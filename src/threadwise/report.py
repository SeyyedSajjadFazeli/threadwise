"""Human-readable rendering: a terminal table, a markdown block, and a bar."""

from __future__ import annotations

import sys

from .bench import Report, WIN_THRESHOLD

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
GREY = "\033[90m"

_ORD = {"serial": "1", "threads": "2", "processes": "3", "async": "4"}


class Style:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self, text: str, *codes: str) -> str:
        if not self.enabled or not codes:
            return text
        return "".join(codes) + text + RESET


def _fmt_s(seconds: float) -> str:
    if seconds != seconds:  # nan
        return "—"
    if seconds >= 1:
        return f"{seconds:.3f} s"
    if seconds >= 0.01:
        return f"{seconds * 1000:.0f} ms"
    return f"{seconds * 1000:.2f} ms"


def _bar(speedup: float, width: int = 14, style: Style | None = None) -> str:
    if speedup != speedup or speedup <= 0:
        return ""
    filled = max(0, min(width, round(speedup / 4 * width)))
    bar = "█" * filled + "·" * (width - filled)
    if style:
        colour = GREEN if speedup >= WIN_THRESHOLD else (YELLOW if speedup > 1.02 else GREY)
        return style(bar, colour)
    return bar


def render_table(r: Report, style: Style) -> str:
    w = r.workload
    lines: list[str] = []
    title = f"threadwise  ·  {w.name}"
    lines.append(style(title, BOLD, CYAN))
    lines.append(style(f"{w.description}", DIM))
    if r.cpu and r.cpu.throttled:
        cpu_txt = (
            f"{r.cpu.logical} cpus visible · {r.cpu.usable:.2f} usable "
            f"({r.cpu.source.split(' (')[0]} limit)"
        )
    else:
        cpu_txt = f"{r.cpu.logical if r.cpu else r.workers} cpus"
    lines.append(
        style(
            f"python {r.python} · {cpu_txt} · {r.tasks} tasks · "
            f"{r.repeat} repeats · median of wall time",
            DIM,
        )
    )
    lines.append("")

    header = f"{'mode':<11}{'time':>10}{'per task':>11}{'speedup':>10}{'eff.':>8}   "
    lines.append(style(header + "vs serial", BOLD))
    lines.append(style("─" * 62, GREY))

    for res in r.results:
        if res.error:
            lines.append(
                f"{res.mode:<11}{'n/a':>10}{'':>11}{'':>10}{'':>8}   "
                + style(res.error, GREY)
            )
            continue
        sp = r.speedup(res)
        eff = r.efficiency(res)
        is_best = (not r.suppressed) and res.mode == r.best_mode and sp >= WIN_THRESHOLD
        label = style(f"{res.mode:<11}", BOLD, GREEN) if is_best else f"{res.mode:<11}"
        sp_txt = f"{sp:>7.2f}×  " if sp == sp else f"{'—':>8}  "
        # Efficiency is speedup/cores: for the baseline it is 1/cores, which
        # reads like a failure. It is not a metric there, so do not print it.
        eff_txt = (
            f"{'—':>6}  "
            if res.mode == "serial"
            else (f"{eff * 100:>5.0f}%  " if eff == eff else f"{'—':>6}")
        )
        colour = GREEN if sp >= WIN_THRESHOLD else (YELLOW if sp > 1.02 else RED if sp < 0.9 else "")
        sp_coloured = style(sp_txt, colour) if colour and sp == sp else sp_txt
        mark = style(" ✓ recommended", GREEN, BOLD) if is_best else ""
        lines.append(
            f"{label}{_fmt_s(res.median):>10}{_fmt_s(res.median / r.tasks):>11}"
            f"{sp_coloured}{eff_txt}{_bar(sp, style=style)}{mark}"
        )

    procs = next((x for x in r.results if x.mode == "processes" and not x.error), None)
    if procs and procs.startup_s:
        lines.append(
            style(
                f"note: process pool startup was {procs.startup_s * 1000:.0f} ms, "
                "measured outside the timed region",
                GREY,
            )
        )

    lines.append("")
    if r.consistent:
        lines.append(style("✓ every mode produced identical results (checksum match)", GREEN))
    else:
        lines.append(style("✗ modes disagree on their output — timings are meaningless", RED))

    lines.append("")
    lines.append(style("verdict", BOLD))
    sp = r.best_speedup
    if r.suppressed:
        lines.append(
            f"  no verdict — only {r.cpu.usable:.2f} CPU is usable here. Every mode is forced to "
            "share one core, so the ranking measures the machine, not your code."
        )
    elif sp >= WIN_THRESHOLD:
        lines.append(
            f"  use {style(r.best_mode, BOLD, GREEN)} — {sp:.2f}× faster than running serially "
            f"across {r.workers} workers."
        )
    else:
        lines.append(
            f"  keep it {style('serial', BOLD)} — the best concurrent mode was only {sp:.2f}×. "
            "Concurrency is not paying for its overhead."
        )

    if r.notes:
        lines.append("")
        lines.append(style("why", BOLD))
        for note in r.notes:
            lines.append(f"  • {note}")
    return "\n".join(lines)


def render_markdown(r: Report) -> str:
    lines = [f"### `{r.workload.name}` — {r.workload.description}", ""]
    lines.append("| mode | median | per task | speedup | efficiency |")
    lines.append("|---|---:|---:|---:|---:|")
    for res in r.results:
        if res.error:
            lines.append(f"| {res.mode} | n/a | — | — | — |")
            continue
        sp = r.speedup(res)
        eff = r.efficiency(res)
        star = " ✅" if (not r.suppressed) and res.mode == r.best_mode and sp >= WIN_THRESHOLD else ""
        eff_txt = "—" if res.mode == "serial" else f"{eff * 100:.0f}%"
        lines.append(
            f"| {res.mode}{star} | {_fmt_s(res.median)} | {_fmt_s(res.median / r.tasks)} | "
            f"{sp:.2f}× | {eff_txt} |"
        )
    lines.append("")
    lines.append(
        f"**Verdict:** {r.best_mode} ({r.best_speedup:.2f}× on {r.workers} cores), "
        f"results identical across modes: {'yes' if r.consistent else 'no'}."
    )
    for note in r.notes:
        lines.append(f"\n> {note}")
    return "\n".join(lines)


def write(r: Report, stream=None, colour: bool | None = None, markdown: bool = False) -> None:
    stream = stream or sys.stdout
    if colour is None:
        colour = stream.isatty()
    style = Style(colour)
    print(render_markdown(r) if markdown else render_table(r, style), file=stream)


def render_sweep(s: "Sweep", style: Style) -> str:  # noqa: F821
    """Terminal view of a scalability sweep: the curve, then the ceiling."""
    from .sweep import Sweep as _S  # local import keeps report.py import-light

    assert isinstance(s, _S)
    lines: list[str] = []
    lines.append(style(f"threadwise sweep  ·  {s.workload.name} · {s.mode}", BOLD, CYAN))
    lines.append(
        style(
            f"{s.tasks} tasks · baseline (serial) {_fmt_s(s.baseline_s)} · median of repeats",
            DIM,
        )
    )
    lines.append("")
    lines.append(style(f"{'workers':>8}{'wall time':>12}{'speedup':>10}{'efficiency':>12}   ", BOLD))
    lines.append(style("─" * 66, GREY))
    peak = max((p.speedup for p in s.points), default=1.0)
    for p in s.points:
        colour = GREEN if p.speedup >= 1.5 else (YELLOW if p.speedup > 1.05 else GREY)
        lines.append(
            f"{p.workers:>8}{_fmt_s(p.median_s):>12}"
            f"{style(f'{p.speedup:>9.2f}×', colour)}{p.efficiency * 100:>11.0f}%   "
            f"{_bar(p.speedup, style=style)}"
        )
    lines.append("")
    if s.fit:
        fit = s.fit
        if fit.max_speedup == float("inf"):
            ceiling = "none found"
        elif fit.is_lower_bound:
            ceiling = f"≥{fit.max_speedup:.0f}× (curve had not bent)"
        else:
            ceiling = f"{fit.max_speedup:.1f}×"
        lines.append(
            f"Amdahl fit: serial fraction {style(f'{fit.serial_fraction * 100:.1f}%', BOLD)}, "
            f"ceiling {style(ceiling, BOLD)}, R² {fit.r2:.3f}"
        )
        if fit.workers_90pct and not fit.is_lower_bound:
            lines.append(f"90% of that ceiling arrives by {style(str(fit.workers_90pct), BOLD)} workers.")
    if s.notes:
        lines.append("")
        lines.append(style("notes", BOLD))
        for n in s.notes:
            lines.append(f"  • {n}")
    return "\n".join(lines)
