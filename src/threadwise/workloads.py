"""Built-in workloads used to characterise a program's concurrency profile.

A workload is a pure function of a *seed*, executed once per task.  Because
every task is independent, the same set of tasks can be executed serially, on
threads, on processes, or as coroutines -- and the results can be compared.

Keeping workloads independent is a deliberate simplification: it lets the
benchmark isolate *where the time goes* rather than also measuring lock
contention.  See the README for what that means for your own code.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# BLAS ships with its own thread pool (often 32-64 threads).  Left alone it
# oversubscribes the machine and makes every number here meaningless.  Pinning
# it to one thread keeps the benchmark about *our* scheduling choice.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

# Calibration constants: sized so one task costs roughly 10-15 ms.
_PURE_ITERS = 60_000
_NUMPY_SIZE = 400
_IO_DELAY_S = 0.02
_DISK_BYTES = 512 * 1024


def _tune_pure(seed: int) -> int:
    """A pure-Python CPU loop: interpreter-bound, so the GIL is held throughout."""
    x = (seed * 2654435761) & 0xFFFFFFFF
    for _ in range(_PURE_ITERS):
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
    return x


def _tune_numpy(seed: int) -> int:
    """A NumPy CPU loop: the heavy lifting happens in C, where the GIL is released."""
    import numpy as np  # imported lazily so the package works without numpy

    rng = np.random.default_rng(seed)
    a = rng.standard_normal((_NUMPY_SIZE, _NUMPY_SIZE))
    b = rng.standard_normal((_NUMPY_SIZE, _NUMPY_SIZE))
    # Several matmuls to make BLAS do measurable work.
    c = a
    for _ in range(3):
        c = c @ b
    return int(c.sum() * 1e6) & 0x7FFFFFFF


def _tune_latency(seed: int) -> int:
    """Simulated I/O latency: the thread sleeps, holding nothing but a slot."""
    time.sleep(_IO_DELAY_S * (1 + seed % 3) / 2)
    return seed * 2


async def _tune_latency_async(seed: int) -> int:
    await asyncio.sleep(_IO_DELAY_S * (1 + seed % 3) / 2)
    return seed * 2


_DISK_DIR = os.environ.get("THREADWISE_TMP") or tempfile.mkdtemp(prefix="threadwise-")


def _tune_disk(seed: int) -> int:
    """Real blocking file I/O: write a blob, read it back, hash it."""
    payload = hashlib.sha256(str(seed).encode()).digest() * (_DISK_BYTES // 32)
    path = os.path.join(_DISK_DIR, f"blob-{seed}.bin")
    try:
        with open(path, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        with open(path, "rb") as fh:
            data = fh.read()
        return int.from_bytes(hashlib.sha256(data).digest()[:4], "big")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


async def _tune_disk_async(seed: int) -> int:
    # There is no portable async file API in the stdlib, so this offloads to a
    # thread.  The benchmark reports it that way rather than pretending.
    return await asyncio.to_thread(_tune_disk, seed)


@dataclass(frozen=True)
class Workload:
    name: str
    kind: str  # "cpu" | "io"
    description: str
    fn: Callable[[int], Any]
    afn: Optional[Callable[[int], Any]] = None
    supports_async: bool = False
    async_notes: str = ""
    tags: tuple[str, ...] = field(default=())


def _registry() -> dict[str, Workload]:
    return {
        "pure-python-cpu": Workload(
            name="pure-python-cpu",
            kind="cpu",
            description="Interpreter-bound arithmetic loop (the classic GIL victim)",
            fn=_tune_pure,
            async_notes="nothing to overlap: CPU work never yields",
            tags=("cpu", "gil"),
        ),
        "numpy-cpu": Workload(
            name="numpy-cpu",
            kind="cpu",
            description="Matrix multiplications: CPU work inside C, GIL released",
            fn=_tune_numpy,
            async_notes="nothing to overlap: CPU work never yields",
            tags=("cpu", "numpy", "gil-released"),
        ),
        "io-latency": Workload(
            name="io-latency",
            kind="io",
            description="Simulated 20-30 ms network-ish latency (sleep-based)",
            fn=_tune_latency,
            afn=_tune_latency_async,
            supports_async=True,
            async_notes="true coroutine suspension, no OS thread per request",
            tags=("io", "network-simulated"),
        ),
        "io-disk": Workload(
            name="io-disk",
            kind="io",
            description="Blocking 512 KB write + fsync + read + hash per task",
            fn=_tune_disk,
            afn=_tune_disk_async,
            supports_async=True,
            async_notes="offloaded with asyncio.to_thread, so it behaves like threads",
            tags=("io", "disk"),
        ),
    }


WORKLOADS: dict[str, Workload] = _registry()


def get(name: str) -> Workload:
    try:
        return WORKLOADS[name]
    except KeyError:
        choices = ", ".join(WORKLOADS)
        raise KeyError(f"unknown workload {name!r}; available: {choices}") from None
