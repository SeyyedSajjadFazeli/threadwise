"""Scalability analysis: how speedup behaves as concurrency grows.

A single number ("7.4x on 8 workers") hides the interesting part.  What you
need to know before shipping is *where the curve bends* and *what it bends
toward*, because that decides how much hardware is worth paying for.

We answer both: measure speedup at a series of worker counts, then fit
Amdahl's model  S(N) = 1 / (s + (1-s)/N)  to find the serial fraction `s`
and the ceiling `1/s` that no amount of concurrency can pass.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .runners import ModeResult, bench_mode
from .workloads import Workload


@dataclass
class SweepPoint:
    workers: int
    median_s: float
    speedup: float
    efficiency: float = 0.0
    stdev_s: float = 0.0

    @classmethod
    def of(cls, workers: int, speedup: float, median_s: float = 1.0) -> "SweepPoint":
        """For synthetic points (tests, predicted curves)."""
        return cls(workers=workers, median_s=median_s, speedup=speedup,
                   efficiency=speedup / workers if workers else 0.0)


@dataclass
class AmdahlFit:
    serial_fraction: float
    max_speedup: float
    r2: float
    workers_90pct: int | None  # workers needed to reach 90% of the ceiling
    # A curve that is still near-linear when the measurement stops has no
    # measurable ceiling: the number above is arithmetic, not evidence.  When
    # this is True the ceiling should be read as "at least".
    is_lower_bound: bool = False


@dataclass
class Sweep:
    workload: Workload
    mode: str
    tasks: int
    baseline_s: float
    points: list[SweepPoint]
    fit: AmdahlFit | None
    cpu_usable: float
    notes: list[str] = field(default_factory=list)

    @property
    def best(self) -> SweepPoint:
        return min(self.points, key=lambda p: p.median_s)

    def to_dict(self) -> dict:
        return {
            "workload": self.workload.name,
            "mode": self.mode,
            "tasks": self.tasks,
            "baseline_s": round(self.baseline_s, 6),
            "points": [
                {
                    "workers": p.workers,
                    "median_s": round(p.median_s, 6),
                    "speedup": round(p.speedup, 3),
                    "efficiency": round(p.efficiency, 3),
                }
                for p in self.points
            ],
            "amdahl": None
            if self.fit is None
            else {
                "serial_fraction": round(self.fit.serial_fraction, 4),
                "max_speedup": None
                if self.fit.max_speedup == float("inf")
                else round(self.fit.max_speedup, 2),
                "max_speedup_is_lower_bound": self.fit.is_lower_bound,
                "r2": round(self.fit.r2, 4),
                "workers_90pct": self.fit.workers_90pct,
            },
            "cpu_usable": self.cpu_usable,
            "notes": self.notes,
        }


def amdahl_speedup(s: float, n: int) -> float:
    return 1.0 / (s + (1.0 - s) / n)


def fit_amdahl(points: list[SweepPoint]) -> AmdahlFit | None:
    """Least-squares fit of the serial fraction.  Grid search is plenty: the
    objective is smooth and one-dimensional, and this avoids a scipy dependency
    for six lines of arithmetic."""
    usable = [p for p in points if p.workers >= 1 and p.speedup == p.speedup]
    if len(usable) < 3:
        return None

    def sse(s: float) -> float:
        return sum((amdahl_speedup(s, p.workers) - p.speedup) ** 2 for p in usable)

    coarse = [i / 1000 for i in range(0, 1001)]
    best = min(coarse, key=sse)
    # Refine around the coarse optimum.
    lo, hi = max(0.0, best - 0.002), min(1.0, best + 0.002)
    fine = [lo + (hi - lo) * i / 200 for i in range(201)]
    s = min(fine, key=sse)

    mean = sum(p.speedup for p in usable) / len(usable)
    ss_tot = sum((p.speedup - mean) ** 2 for p in usable) or 1e-12
    r2 = max(0.0, 1 - sse(s) / ss_tot)
    ceiling = 1 / s if s > 1e-6 else math.inf
    w90 = None
    if math.isfinite(ceiling):
        target = 0.9 * ceiling
        n = 1
        # Only claim a worker count we could plausibly reach: extrapolating
        # "1024 workers" from five points is arithmetic, not evidence.
        limit = max(p.workers for p in usable) * 8
        while n <= limit:
            if amdahl_speedup(s, n) >= target:
                w90 = n
                break
            n *= 2
    last = max(usable, key=lambda p: p.workers)
    peak = max(p.speedup for p in usable)
    # Two ways a fit outruns its evidence: the curve is still straight, or the
    # claimed ceiling sits far beyond anything we measured.
    no_bend = (
        last.efficiency >= 0.90
        or s < 0.005
        or (math.isfinite(ceiling) and ceiling > peak * 3.0)
    )
    return AmdahlFit(
        serial_fraction=s,
        max_speedup=ceiling,
        r2=r2,
        workers_90pct=w90,
        is_lower_bound=no_bend,
    )


def run_sweep(
    w: Workload,
    mode: str = "threads",
    worker_counts: tuple[int, ...] = (1, 2, 4, 8, 16),
    tasks: int | None = None,
    repeat: int = 3,
    warmup: int = 1,
    cpu_usable: float = 1.0,
) -> Sweep:
    counts = sorted({n for n in worker_counts if n >= 1})
    if not counts:
        raise ValueError("worker counts must contain at least one value >= 1")
    tasks = tasks or max(16, counts[-1] * (6 if w.kind == "io" else 3))
    items = list(range(1, tasks + 1))

    points: list[SweepPoint] = []
    baseline = 0.0
    for n in counts:
        res: ModeResult = bench_mode(w, mode, items, repeat=repeat, warmup=warmup, workers=n)
        if res.error or not res.samples:
            continue
        if n == 1 or baseline == 0.0:
            baseline = res.median if baseline == 0.0 else baseline
        points.append(
            SweepPoint(
                workers=n,
                median_s=res.median,
                speedup=(baseline / res.median) if baseline else 1.0,
                efficiency=(baseline / res.median) / n if baseline else 0.0,
                stdev_s=res.stdev,
            )
        )
    if not points:
        raise RuntimeError("sweep produced no measurements")

    fit = fit_amdahl(points)
    # Fitting a curve on a machine that can only run one task at a time yields
    # "100% serial" — arithmetic dressed up as insight. Refuse instead.
    if w.kind == "cpu" and cpu_usable < 1.5:
        fit = None

    sweep = Sweep(
        workload=w,
        mode=mode,
        tasks=tasks,
        baseline_s=baseline,
        points=points,
        fit=fit,
        cpu_usable=cpu_usable,
    )
    sweep.notes = _sweep_notes(sweep)
    return sweep


def _sweep_notes(s: Sweep) -> list[str]:
    notes: list[str] = []
    if s.workload.kind == "cpu" and s.cpu_usable < 1.5:
        return [
            f"only {s.cpu_usable:.2f} CPU usable: every point on this curve is bounded by one "
            "core, so it measures queueing, not parallelism. Nothing here is evidence about "
            "your code — run the sweep where you have real cores."
        ]
    if s.fit is None:
        if s.workload.kind == "cpu" and s.cpu_usable < 1.5:
            notes.append(
                "no fit attempted: a CPU sweep on one usable core only measures queueing. "
                "Run this on a machine with real cores."
            )
        else:
            notes.append("not enough points for an Amdahl fit")
        return notes

    fit = s.fit
    peak = max(p.speedup for p in s.points)
    last = s.points[-1]
    if last.efficiency < 0.55 and len(s.points) > 2:
        notes.append(
            f"efficiency has fallen to {last.efficiency * 100:.0f}% at {last.workers} workers: "
            "extra workers are idle or fighting each other. Find the bend before you add capacity."
        )
    if fit.is_lower_bound:
        notes.append(
            f"no measurable ceiling: at {last.workers} workers the curve is still "
            f"{last.efficiency * 100:.0f}% efficient and the fitted {fit.max_speedup:.0f}x sits "
            f"well past the {peak:.1f}x we actually measured. Read it as a lower bound; sweep "
            "another doubling if you need to know where it bends."
        )
    elif fit.serial_fraction >= 0.02:
        notes.append(
            f"the fit puts {fit.serial_fraction * 100:.1f}% of the work on the serial path, "
            f"capping this approach at {fit.max_speedup:.1f}x however many cores you buy."
        )
    else:
        notes.append(
            f"almost no serial bottleneck ({fit.serial_fraction * 100:.1f}%), but the curve has "
            f"already bent: efficiency is {last.efficiency * 100:.0f}% at {last.workers} workers, "
            "so something other than the serial fraction is costing you."
        )
    if fit.workers_90pct and not fit.is_lower_bound and last.workers >= fit.workers_90pct:
        notes.append(
            f"90% of the achievable speedup arrives by {fit.workers_90pct} workers — past that "
            "you are paying for the last 10%."
        )
    if peak >= 1.5 and peak > last.speedup * 1.1:
        notes.append(
            f"speedup peaked at {peak:.2f}x and then fell back to {last.speedup:.2f}x: the curve "
            "turned downward, which is contention, not a lack of cores."
        )
    return notes
