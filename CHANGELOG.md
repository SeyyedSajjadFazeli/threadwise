# Changelog

## 1.1.0 — 2026-11-16

### Added
- `threadwise sweep` — measures speedup across worker counts and fits Amdahl's
  law to report the serial fraction, the ceiling, and fit quality.
- `--html PATH` for both `bench` and `sweep`: a self-contained report with
  inline SVG charts, no CDN, no external assets, print-ready.
- Cost model: estimates per-task process overhead and predicts whether larger
  tasks would beat more workers.
- Decision layer: every report opens with a one-line recommendation and reason,
  or an explicit refusal.

### Changed
- Amdahl ceilings are now labelled `≥` (lower bound) when the curve has not
  bent inside the measured range, instead of presenting extrapolation as fact.
- `threadwise modes` reports cgroup-aware usable CPU rather than raw cores.


## 1.0.0 — 2026-11-16

First release.

- Four execution modes: `serial`, `threads`, `processes`, `async`.
- Four built-in workloads: `pure-python-cpu`, `numpy-cpu`, `io-latency`, `io-disk`.
- Benchmark your own code with `threadwise bench ./script.py` (`run(seed)`, optional `arun(seed)` and `KIND`).
- Result checksums: modes that disagree are reported instead of ranked.
- cgroup-aware CPU budget: reports *usable* CPUs and suppresses CPU verdicts on ~1-core machines.
- BLAS thread count pinned to 1 so measurements reflect scheduling, not oversubscription.
- Human-readable table, markdown, and JSON output.
