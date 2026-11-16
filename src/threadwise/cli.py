"""Command line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .bench import run_benchmark
from .loader import LoadError, load_script
from .htmlreport import write_html
from .report import Style, write
from .runners import MODES, cpu_budget
from .workloads import WORKLOADS, get

EPILOG = """examples:
  threadwise bench                          # all built-in workloads
  threadwise bench pure-python-cpu          # one workload
  threadwise bench ./parse_invoices.py      # your own script
  threadwise bench --json > bench.json      # machine-readable output
  threadwise bench -w 4 -r 5 --all          # 4 workers, 5 repeats
"""


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="threadwise",
        description="Find out whether your Python should be serial, threaded, "
        "multi-process, or async — measured, not guessed.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"threadwise {__version__}")
    sub = p.add_subparsers(dest="command")

    b = sub.add_parser("bench", help="run the benchmark")
    b.add_argument(
        "target",
        nargs="?",
        help="a built-in workload name or a path to a Python script defining run(seed)",
    )
    b.add_argument("--all", action="store_true", help="bench every built-in workload")
    b.add_argument(
        "-w",
        "--workers",
        type=int,
        default=None,
        help="concurrency (default: usable CPUs for cpu work, up to 32 for I/O)",
    )
    b.add_argument("-n", "--tasks", type=int, default=None, help="number of tasks in the job")
    b.add_argument("-r", "--repeat", type=int, default=3, help="timed repeats per mode (default 3)")
    b.add_argument("--warmup", type=int, default=1, help="untimed warmup runs (default 1)")
    b.add_argument("--modes", default=",".join(MODES), help="comma-separated subset of modes")
    b.add_argument("--json", action="store_true", help="print JSON instead of a table")
    b.add_argument("--html", metavar="PATH", help="write a standalone HTML report")
    b.add_argument("--markdown", "--md", action="store_true", help="print a markdown block")
    b.add_argument("--no-color", action="store_true", help="disable ANSI colour")

    sw = sub.add_parser("sweep", help="measure speedup across worker counts (scalability)")
    sw.add_argument("target", nargs="?", help="built-in workload name or script path")
    sw.add_argument("--mode", default=None, help="mode to sweep (default: threads, io->async)")
    sw.add_argument("--sizes", default="1,2,4,8,16", help="comma-separated worker counts")
    sw.add_argument("-n", "--tasks", type=int, default=None, help="tasks per run")
    sw.add_argument("-r", "--repeat", type=int, default=2, help="timed repeats per point")
    sw.add_argument("--warmup", type=int, default=1, help="untimed warmup runs")
    sw.add_argument("--json", action="store_true", help="print JSON")
    sw.add_argument("--html", metavar="PATH", help="write a standalone HTML report")

    sub.add_parser("workloads", help="list built-in workloads")
    sub.add_parser("modes", help="explain the four modes")
    return p.parse_args(argv)


def _resolve(target: str | None, all_: bool) -> list:
    if all_ or target is None:
        return list(WORKLOADS.values())
    if target in WORKLOADS:
        return [get(target)]
    if target.endswith(".py") or Path(target).exists():
        return [load_script(target)]
    raise LoadError(
        f"{target!r} is not a built-in workload and not a file. "
        f"Try one of: {', '.join(WORKLOADS)}"
    )


def _list_workloads() -> None:
    style = Style(True)
    print(style("Built-in workloads", "1"))
    for w in WORKLOADS.values():
        async_mark = "async ✓" if w.supports_async else "async n/a"
        print(f"  {w.name:<18} {w.kind:<4} {async_mark:<9} {w.description}")
    print("\nAny Python file with `def run(seed): ...` works too:  threadwise bench ./job.py")


def _explain_modes() -> None:
    rows = [
        ("serial", "one task after another, in this process", "baseline for every speedup"),
        ("threads", "many tasks at once, one interpreter, one GIL",
         "good for I/O, useless for pure-Python CPU work"),
        ("processes", "many interpreters, real parallel cores",
         "good for CPU work, pays pickling and startup"),
        ("async", "many tasks on one event loop, no OS thread each",
         "best for high-concurrency network I/O"),
    ]
    print(f"{'mode':<11}{'what it does':<52}when it wins")
    print("─" * 110)
    for mode, what, when in rows:
        print(f"{mode:<11}{what:<52}{when}")
    budget = cpu_budget()
    limit = f"about {budget.usable:.2f} usable" if budget.throttled else f"{budget.usable:.0f}"
    print(
        f"\nThis machine has {limit} CPUs ({budget.source}), so processes can reach at most "
        f"~{budget.usable:.1f}× on CPU-bound work."
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.command in (None, "bench") and args.command is None:
        _parse_args(["--help"])
        return 0

    if args.command == "sweep":
        return _run_sweep(args)

    if args.command == "workloads":
        _list_workloads()
        return 0
    if args.command == "modes":
        _explain_modes()
        return 0

    try:
        workloads = _resolve(args.target, getattr(args, "all", False))
    except LoadError as exc:
        print(f"threadwise: {exc}", file=sys.stderr)
        return 2

    modes = tuple(m.strip() for m in args.modes.split(",") if m.strip())
    unknown = [m for m in modes if m not in MODES]
    if unknown:
        print(f"threadwise: unknown mode(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    html_path = getattr(args, "html", None)
    reports = []
    for index, w in enumerate(workloads):
        report = run_benchmark(
            w,
            tasks=args.tasks,
            workers=args.workers,
            repeat=args.repeat,
            warmup=args.warmup,
            modes=modes,
        )
        reports.append(report)
        if not args.json and not html_path:
            if index:
                print()
            write(
                report,
                colour=False if args.no_color or args.json else None,
                markdown=args.markdown,
            )

    if html_path:
        from .htmlreport import write_html as _wh

        if len(reports) == 1:
            _wh(html_path, report=reports[0])
        else:
            _wh(html_path, reports=reports)
        if not args.json:
            print(f"wrote {html_path}")

    if args.json:
        import json

        payload = reports[0].to_dict() if len(reports) == 1 else {
            "tool": "threadwise",
            "version": __version__,
            "reports": [r.to_dict() for r in reports],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))

    # Exit code 0 always: this is a measuring tool, not a linter gate.
    return 0


def _run_sweep(args) -> int:
    import json

    from .sweep import run_sweep

    try:
        targets = _resolve(args.target, False)
    except LoadError as exc:
        print(f"threadwise: {exc}", file=sys.stderr)
        return 2
    w = targets[0]
    mode = args.mode or ("async" if (w.kind == "io" and w.supports_async) else "threads")
    if w.kind == "io" and mode == "async" and not w.supports_async:
        mode = "threads"
    if w.kind == "cpu" and mode in ("async",):
        print(f"threadwise: {mode} cannot run CPU work", file=sys.stderr)
        return 2
    try:
        sizes = tuple(int(x) for x in args.sizes.split(",") if x.strip())
    except ValueError:
        print("threadwise: --sizes must be integers like 1,2,4,8", file=sys.stderr)
        return 2

    budget = cpu_budget()
    sweep = run_sweep(
        w,
        mode=mode,
        worker_counts=sizes,
        tasks=args.tasks,
        repeat=args.repeat,
        warmup=args.warmup,
        cpu_usable=budget.usable,
    )
    if args.html:
        write_html(args.html, sweep=sweep, title="scalability sweep")
        if not args.json:
            print(f"wrote {args.html}")
    if args.json:
        payload = {"tool": "threadwise", "version": __version__, "sweep": sweep.to_dict()}
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    if args.html:
        return 0

    from .report import Style, render_sweep

    print(render_sweep(sweep, Style(sys.stdout.isatty())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
