"""Benchmark orchestration and the part that actually matters: the verdict."""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import dataclass, field
from typing import Any

from .runners import MODES, CpuBudget, ModeResult, bench_mode, cpu_budget, default_workers
from .workloads import Workload

# A mode must be this much faster than serial before we recommend it.
WIN_THRESHOLD = 1.15
# Below this, we call it a tie.
TIE_THRESHOLD = 1.07


@dataclass
class Report:
    workload: Workload
    tasks: int
    workers: int
    repeat: int
    warmup: int
    results: list[ModeResult]
    baseline_s: float
    consistent: bool
    python: str
    platform: str
    cpu: CpuBudget | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def suppressed(self) -> bool:
        """True when the machine cannot support a CPU verdict: one core means
        no concurrent mode *can* win, so recommending one would be noise."""
        return (
            self.workload.kind == "cpu"
            and self.cpu is not None
            and self.cpu.usable < 1.5
            and self.workers <= 1
        )

    @property
    def best_mode(self) -> str:
        # Rank by best-case time; a mode that only wins on one noisy repeat is
        # not a mode you should ship.
        best = self._best_result()
        return best.mode if best else "serial"

    def _best_result(self) -> ModeResult | None:
        usable = [r for r in self.results if not r.error and r.samples]
        return min(usable, key=lambda r: r.best) if usable else None

    @property
    def best_speedup(self) -> float:
        """Speedup of the recommended mode, so the verdict and the table agree."""
        best = self._best_result()
        return self.speedup(best) if best else 1.0

    def speedup(self, r: ModeResult) -> float:
        if r.error or not r.samples or self.baseline_s <= 0:
            return float("nan")
        return self.baseline_s / r.median

    def efficiency(self, r: ModeResult) -> float:
        sp = self.speedup(r)
        return sp / self.workers if self.workers else float("nan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": "threadwise",
            "version": __import__("threadwise").__version__,
            "workload": {
                "name": self.workload.name,
                "kind": self.workload.kind,
                "description": self.workload.description,
            },
            "env": {
                "python": self.python,
                "platform": self.platform,
                "cpus": self.workers,
            },
            "config": {"tasks": self.tasks, "repeat": self.repeat, "warmup": self.warmup},
            "results": [
                {
                    "mode": r.mode,
                    "median_s": round(r.median, 6) if r.samples else None,
                    "best_s": round(r.best, 6) if r.samples else None,
                    "stdev_s": round(r.stdev, 6) if r.samples else None,
                    "per_task_ms": round(r.median / self.tasks * 1000, 3)
                    if r.samples and self.tasks
                    else None,
                    "startup_ms": round(r.startup_s * 1000, 2),
                    "speedup": round(self.speedup(r), 3) if not r.error else None,
                    "efficiency": round(self.efficiency(r), 3)
                    if not r.error and self.workers
                    else None,
                    "checksum": r.checksum or None,
                    "error": r.error,
                }
                for r in self.results
            ],
            "verdict": {
                "recommended": None if self.suppressed else self.best_mode,
                "speedup": round(self.best_speedup, 2),
                "results_identical": self.consistent,
            },
            "notes": self.notes,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


def run_benchmark(
    w: Workload,
    tasks: int | None = None,
    workers: int | None = None,
    repeat: int = 3,
    warmup: int = 1,
    modes: tuple[str, ...] = MODES,
) -> Report:
    workers = workers or default_workers(w.kind)
    if tasks is None:
        # Small jobs are dominated by scheduling, so give each worker a few
        # tasks; I/O tasks are cheap to queue, so allow more of them.
        per_worker = 8 if w.kind == "io" else 4
        tasks = min(96, max(4, workers * per_worker))
    items = list(range(1, tasks + 1))

    results = [
        bench_mode(w, m, items, repeat=repeat, warmup=warmup, workers=workers) for m in modes
    ]
    baseline = next((r.median for r in results if r.mode == "serial" and r.samples), 0.0)
    sums = {r.checksum for r in results if r.checksum}
    consistent = len(sums) <= 1

    report = Report(
        workload=w,
        tasks=tasks,
        workers=workers,
        repeat=repeat,
        warmup=warmup,
        results=results,
        baseline_s=baseline,
        consistent=consistent,
        python=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        platform=platform.platform(terse=True),
        cpu=cpu_budget(),
    )
    report.notes = _explain(report)
    return report


def _explain(r: Report) -> list[str]:
    notes: list[str] = []
    by = {x.mode: x for x in r.results}
    threads = by.get("threads")
    procs = by.get("processes")
    async_ = by.get("async")

    if not r.consistent:
        notes.append(
            "WARNING: modes returned different results. Fix correctness before trusting these timings."
        )

    # A single usable core makes CPU concurrency verdicts meaningless, so say
    # that before saying anything else.  I/O is different: waiting needs no core.
    if r.workload.kind == "cpu" and r.cpu is not None and r.cpu.usable < 1.5:
        notes.append(
            f"only {r.cpu.usable:.2f} CPU is usable ({r.cpu.source}), so no mode can be faster "
            "than serial for CPU work here. Re-run where you have real cores; this run says "
            "nothing about your workload's shape."
        )
        return notes

    if r.workload.kind == "cpu":
        if threads and procs and not threads.error and not procs.error:
            ts, ps = r.speedup(threads), r.speedup(procs)
            if ts < 1.1:
                notes.append(
                    f"Threads gave {ts:.2f}x because the work runs in the CPython interpreter, "
                    "which holds the GIL: threads queue instead of running side by side."
                )
            if ps >= 1.5:
                notes.append(
                    f"Processes gave {ps:.2f}x on {r.workers} cores. Pure Python parallelises, "
                    "but remember every argument and result is pickled across the process boundary."
                )
            elif ps < 1.15:
                notes.append(
                    f"Processes only reached {ps:.2f}x: each task is too small to pay for process "
                    "startup and pickling. Make the tasks bigger, not the pool."
                )
            if ts >= 1.15 and ps >= ts:
                notes.append(
                    "The interesting one: threads also improved, because the heavy work happens "
                    "inside C (NumPy/BLAS) where the GIL is released."
                )
        if async_ and async_.error:
            notes.append(
                "async is n/a for CPU work: there is no I/O to suspend on, so an event loop "
                "would only add overhead."
            )
    else:
        if threads and not threads.error:
            ts = r.speedup(threads)
            if async_ and not async_.error and r.speedup(async_) > ts * 1.05:
                notes.append(
                    f"async beat threads ({r.speedup(async_):.2f}x vs {ts:.2f}x): each request is "
                    "a lightweight coroutine instead of an OS thread."
                )
            elif ts >= 1.15:
                notes.append(
                    f"Threads gave {ts:.2f}x: waiting on I/O costs no CPU, so the GIL is not the "
                    "bottleneck. Concurrency is enough; you do not need processes."
                )
        if procs and not procs.error and r.speedup(procs) < 1.2:
            notes.append(
                "Processes do not help I/O-bound code: spawning and pickling cost more than the wait."
            )
    if r.workload.async_notes and async_ and not async_.error:
        notes.append(f"async note: {r.workload.async_notes}.")
    return notes
