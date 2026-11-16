"""Load a user's script as a workload: `threadwise bench ./my_script.py`."""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

from .workloads import Workload


class LoadError(RuntimeError):
    pass


def _declared_kind(source: str, default: str = "cpu") -> str:
    """Read module-level KIND = "cpu"|"io" without executing anything extra."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return default
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("KIND", "WORKLOAD_KIND"):
                    if isinstance(node.value, ast.Constant) and node.value.value in ("cpu", "io"):
                        return node.value.value
    return default


def load_script(path: str | Path) -> Workload:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise LoadError(f"no such file: {path}")
    source = path.read_text(encoding="utf-8")
    kind = _declared_kind(source)

    name = f"script:{path.name}"
    spec = importlib.util.spec_from_file_location(f"_threadwise_script_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise LoadError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise LoadError(f"importing {path.name} failed: {type(exc).__name__}: {exc}") from exc

    fn = getattr(module, "run", None) or getattr(module, "main", None)
    if fn is None or not callable(fn):
        raise LoadError(
            f"{path.name} must define `def run(seed): ...` — one independent unit of work per call."
        )
    afn = getattr(module, "arun", None)
    supports_async = callable(afn)
    if not supports_async and callable(getattr(module, "run_async", None)):
        afn = getattr(module, "run_async")
        supports_async = True

    return Workload(
        name=name,
        kind=kind,
        description=getattr(module, "DESCRIPTION", f"custom script {path.name}") or path.name,
        fn=fn,
        afn=afn if supports_async else None,
        supports_async=supports_async,
        async_notes="uses the coroutine you provided as arun(seed)"
        if supports_async
        else "no async form",
        tags=("custom",),
    )
