"""Execution engines.  Each one runs the same task list and times only the work."""

from __future__ import annotations

import asyncio
import hashlib
import multiprocessing as mp
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Iterable

from .workloads import Workload

MODES = ("serial", "threads", "processes", "async")


def checksum(results: Iterable[Any]) -> str:
    h = hashlib.sha256()
    for value in results:
        h.update(repr(value).encode("utf-8", "replace"))
        h.update(b"|")
    return h.hexdigest()[:12]


def _mp_context() -> mp.context.BaseContext:
    # fork avoids re-importing the caller's module, which is what makes
    # `threadwise bench my_script.py` work without packaging the script.
    methods = mp.get_all_start_methods()
    return mp.get_context("fork" if "fork" in methods else "spawn")


@dataclass
class ModeResult:
    mode: str
    samples: list[float]  # per-repeat wall time for the whole job, seconds
    startup_s: float  # engine setup outside the timed region (pool/executor)
    checksum: str
    error: str | None = None

    @property
    def median(self) -> float:
        return statistics.median(self.samples) if self.samples else float("nan")

    @property
    def best(self) -> float:
        return min(self.samples) if self.samples else float("nan")

    @property
    def stdev(self) -> float:
        return statistics.stdev(self.samples) if len(self.samples) > 1 else 0.0


def _job_serial(w: Workload, items: list[int]) -> list[Any]:
    return [w.fn(s) for s in items]


def _bench_serial(w: Workload, items: list[int], repeat: int, warmup: int) -> ModeResult:
    for _ in range(warmup):
        _job_serial(w, items)
    samples, sums = [], []
    for _ in range(repeat):
        t0 = time.perf_counter()
        out = _job_serial(w, items)
        samples.append(time.perf_counter() - t0)
        sums = out
    return ModeResult("serial", samples, 0.0, checksum(sums))


def _bench_threads(
    w: Workload, items: list[int], repeat: int, warmup: int, workers: int
) -> ModeResult:
    t0 = time.perf_counter()
    pool = ThreadPoolExecutor(max_workers=workers)
    startup = time.perf_counter() - t0
    try:
        for _ in range(warmup):
            list(pool.map(w.fn, items))
        samples, out = [], []
        for _ in range(repeat):
            t0 = time.perf_counter()
            out = list(pool.map(w.fn, items))
            samples.append(time.perf_counter() - t0)
    finally:
        pool.shutdown(wait=True)
    return ModeResult("threads", samples, startup, checksum(out))


def _bench_processes(
    w: Workload, items: list[int], repeat: int, warmup: int, workers: int
) -> ModeResult:
    ctx = _mp_context()
    t0 = time.perf_counter()
    pool = ctx.Pool(processes=workers)
    startup = time.perf_counter() - t0
    try:
        for _ in range(warmup):
            pool.map(w.fn, items, chunksize=1)
        samples, out = [], []
        for _ in range(repeat):
            t0 = time.perf_counter()
            out = pool.map(w.fn, items, chunksize=1)
            samples.append(time.perf_counter() - t0)
    finally:
        pool.close()
        pool.join()
    return ModeResult("processes", samples, startup, checksum(out))


async def _async_job(w: Workload, items: list[int], workers: int) -> list[Any]:
    sem = asyncio.Semaphore(workers)

    async def one(seed: int) -> Any:
        async with sem:
            return await w.afn(seed)  # type: ignore[misc]

    return await asyncio.gather(*(one(s) for s in items))


def _bench_async(
    w: Workload, items: list[int], repeat: int, warmup: int, workers: int
) -> ModeResult:
    for _ in range(warmup):
        asyncio.run(_async_job(w, items, workers))
    samples, out = [], []
    for _ in range(repeat):
        t0 = time.perf_counter()
        out = asyncio.run(_async_job(w, items, workers))
        samples.append(time.perf_counter() - t0)
    return ModeResult("async", samples, 0.0, checksum(out))


def bench_mode(
    w: Workload,
    mode: str,
    items: list[int],
    repeat: int,
    warmup: int,
    workers: int,
) -> ModeResult:
    """Run one mode, converting a crash into a result with `error` set."""
    if mode == "async" and not w.supports_async:
        return ModeResult(mode, [], 0.0, "", error="no async form for this workload")
    try:
        if mode == "serial":
            return _bench_serial(w, items, repeat, warmup)
        if mode == "threads":
            return _bench_threads(w, items, repeat, warmup, workers)
        if mode == "processes":
            return _bench_processes(w, items, repeat, warmup, workers)
        if mode == "async":
            return _bench_async(w, items, repeat, warmup, workers)
    except Exception as exc:  # pragma: no cover - depends on platform
        return ModeResult(mode, [], 0.0, "", error=f"{type(exc).__name__}: {exc}")
    raise ValueError(f"unknown mode {mode!r}")


def default_workers(kind: str = "cpu") -> int:
    """How many concurrent slots to use by default.

    CPU work is bounded by usable cores, so oversubscribing only adds context
    switching.  I/O work is bounded by the outside world instead: a sleeping
    task costs no CPU, so a 1-core container can still serve 16 concurrent
    requests.  Conflating the two is the mistake this tool exists to stop.
    """
    budget = cpu_budget()
    if kind == "io":
        return max(1, min(32, budget.logical))
    return max(1, int(budget.usable))


@dataclass(frozen=True)
class CpuBudget:
    """How much CPU this process can actually use, which is often not what
    os.cpu_count() claims.  Containers, cgroups and CI runners all lie."""

    logical: int
    quota: float | None  # None = no limit found
    source: str

    @property
    def usable(self) -> float:
        if self.quota is None:
            return float(self.logical)
        return max(0.25, min(float(self.logical), self.quota))

    @property
    def throttled(self) -> bool:
        return self.quota is not None and self.quota < self.logical - 0.01


def _affinity() -> int:
    try:
        return len(os.sched_getaffinity(0))  # type: ignore[attr-defined]
    except AttributeError:
        return os.cpu_count() or 1


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="ascii") as fh:
            return fh.read().strip()
    except OSError:
        return None


def cpu_budget(cgroup_root: str = "/sys/fs/cgroup") -> CpuBudget:
    """`cgroup_root` is injectable so the parsing logic can be unit-tested."""
    logical = _affinity()

    # cgroup v2: "<quota> <period>", quota may be "max".
    for path in (f"{cgroup_root}/cpu.max", f"{cgroup_root}/cpu/cpu.max"):
        raw = _read(path)
        if raw:
            parts = raw.split()
            if len(parts) == 2 and parts[0] != "max":
                try:
                    quota = int(parts[0]) / int(parts[1])
                    return CpuBudget(logical, quota, "cgroup v2")
                except (ValueError, ZeroDivisionError):
                    pass
            if parts and parts[0] == "max":
                return CpuBudget(logical, None, "cgroup v2")

    # cgroup v1: quota and period in separate files.
    quota_raw = _read(f"{cgroup_root}/cpu/cpu.cfs_quota_us")
    period_raw = _read(f"{cgroup_root}/cpu/cpu.cfs_period_us")
    if quota_raw and period_raw:
        try:
            q = int(quota_raw)
            if q > 0:
                return CpuBudget(logical, q / int(period_raw), "cgroup v1")
        except (ValueError, ZeroDivisionError):
            pass

    return CpuBudget(logical, None, "no cgroup limit")


def cpu_count() -> int:
    return int(cpu_budget().usable)
