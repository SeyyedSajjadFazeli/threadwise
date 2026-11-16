"""Turning measurements into decisions.

Two questions the raw table cannot answer:

1. *Would batching the work change the answer?*  Process modes pay a fixed
   cost per task (pickling, dispatch).  Measuring that cost lets us predict
   the speedup for a task size other than the one we happened to test.
2. *What does this cost us in practice?*  A 7x speedup on a job that already
   takes 40 ms is irrelevant; a 2x on a 20-minute job is a coffee break.
"""

from __future__ import annotations

from dataclasses import dataclass

from .bench import Report


@dataclass
class CostModel:
    """Overhead per task, in seconds, derived from the process-mode result.

    A process task costs (work / cores) + overhead.  With two points (serial
    and process medians) we can solve for overhead directly.
    """

    per_task_work_s: float
    per_task_overhead_s: float

    @property
    def break_even_workers(self) -> float:
        """Below this many workers, processes cannot win at this task size."""
        if self.per_task_overhead_s <= 0:
            return 1.0
        return 1.0 + self.per_task_overhead_s / self.per_task_work_s

    def speedup_at(self, workers: int, task_scale: float = 1.0) -> float:
        """Predicted process speedup if every task did `task_scale` times the work."""
        work = self.per_task_work_s * task_scale
        per_task = work / workers + self.per_task_overhead_s
        return self.per_task_work_s / per_task * workers if per_task else 1.0


def cost_model(r: Report) -> CostModel | None:
    by = {x.mode: x for x in r.results}
    serial, procs = by.get("serial"), by.get("processes")
    if not serial or not procs or serial.error or procs.error or not serial.samples:
        return None
    if not procs.samples or not r.tasks:
        return None
    work = serial.median / r.tasks
    # process wall time = startup + tasks*(work/workers + overhead)
    observed = (procs.median - procs.startup_s) / r.tasks - work / r.workers
    return CostModel(per_task_work_s=work, per_task_overhead_s=max(0.0, observed))


def human_time(seconds: float) -> str:
    if seconds < 1e-3:
        return f"{seconds * 1e6:.0f} µs"
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 90:
        return f"{seconds:.1f} s"
    if seconds < 5400:
        return f"{seconds / 60:.1f} min"
    return f"{seconds / 3600:.1f} h"


def practical_gain(r: Report) -> str:
    """What the recommendation saves on the job as measured."""
    best = r._best_result()
    if not best or not r.baseline_s:
        return ""
    saved = r.baseline_s - best.median
    pct = saved / r.baseline_s * 100
    return (
        f"{human_time(r.baseline_s)} → {human_time(best.median)} "
        f"({pct:.0f}% less wall time on this job)"
    )


def batching_advice(r: Report) -> str | None:
    """Only worth saying when the process overhead is a real fraction of the work.

    For I/O workloads the "overhead" derived this way is not a cost — the task
    is mostly waiting, so the arithmetic says nothing.  Stay quiet there.
    """
    model = cost_model(r)
    if model is None or r.workload.kind != "cpu":
        return None
    if model.per_task_work_s <= 0 or model.per_task_overhead_s < 1e-6:
        return None
    ratio = model.per_task_overhead_s / model.per_task_work_s
    if ratio < 0.15:
        return None
    larger = 4.0
    predicted = model.speedup_at(r.workers, task_scale=larger)
    current = next(
        (r.speedup(x) for x in r.results if x.mode == "processes" and not x.error), float("nan")
    )
    if predicted <= current * 1.2:
        return None
    return (
        f"each process task carries {human_time(model.per_task_overhead_s)} of overhead against "
        f"{human_time(model.per_task_work_s)} of work. Batch {larger:.0f}× more work per task and "
        f"the same pool should reach about {predicted:.1f}x instead of {current:.2f}x — you do not "
        "need more cores, you need bigger tasks."
    )


def decision(r: Report) -> tuple[str, str]:
    """One-line decision plus the reason, for the top of any report."""
    best = r._best_result()
    if r.suppressed:
        return (
            "Not enough CPU to decide",
            "This machine cannot run two tasks at once, so no concurrency result here is evidence.",
        )
    if not best:
        return ("No usable measurement", "Every mode failed or was unavailable.")
    sp = r.speedup(best)
    if sp < 1.15:
        return (
            f"Keep it serial",
            f"Best concurrent option was {sp:.2f}x — not worth the complexity at this task size.",
        )
    mode_reason = {
        "threads": "threads overlap the waiting without copying data between processes",
        "processes": "separate interpreters give real parallel cores",
        "async": "one event loop handles the wait with no thread per task",
        "serial": "running one task at a time is already the best option",
    }.get(best.mode, best.mode)
    return (f"Use {best.mode}", f"{sp:.2f}x faster, because {mode_reason}.")
