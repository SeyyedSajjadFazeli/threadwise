"""threadwise — measure whether your Python should be threaded, forked, or async."""

__version__ = "1.1.0"

from .bench import Report, run_benchmark  # noqa: E402,F401
from .htmlreport import render_html  # noqa: E402,F401
from .sweep import Sweep, amdahl_speedup, fit_amdahl, run_sweep  # noqa: E402,F401
from .workloads import WORKLOADS, Workload, get  # noqa: E402,F401

__all__ = [
    "__version__",
    "Report",
    "run_benchmark",
    "Sweep",
    "run_sweep",
    "fit_amdahl",
    "amdahl_speedup",
    "render_html",
    "WORKLOADS",
    "Workload",
    "get",
]
