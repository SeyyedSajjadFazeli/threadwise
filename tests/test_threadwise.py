"""Tests for threadwise.  Run with:  python -m unittest discover -s tests -v"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from threadwise import __version__  # noqa: E402
from threadwise.bench import Report, run_benchmark  # noqa: E402
from threadwise.cli import main  # noqa: E402
from threadwise.loader import LoadError, load_script  # noqa: E402
from threadwise.report import render_markdown, render_table, Style  # noqa: E402
from threadwise.runners import CpuBudget, cpu_budget  # noqa: E402
from threadwise.workloads import WORKLOADS, get  # noqa: E402


class CpuBudgetParsing(unittest.TestCase):
    def _root(self, files: dict[str, str]) -> str:
        root = tempfile.mkdtemp(prefix="cg-")
        for rel, content in files.items():
            path = Path(root, rel)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        return root

    def test_cgroup_v2_quota(self):
        root = self._root({"cpu.max": "150000 100000\n"})
        b = cpu_budget(root)
        self.assertAlmostEqual(b.quota, 1.5)
        self.assertTrue(b.throttled)
        self.assertLessEqual(b.usable, 1.5)

    def test_cgroup_v2_unlimited(self):
        root = self._root({"cpu.max": "max 100000\n"})
        b = cpu_budget(root)
        self.assertIsNone(b.quota)
        self.assertFalse(b.throttled)

    def test_cgroup_v1_quota(self):
        root = self._root(
            {"cpu/cpu.cfs_quota_us": "200000\n", "cpu/cpu.cfs_period_us": "100000\n"}
        )
        b = cpu_budget(root)
        self.assertAlmostEqual(b.quota, 2.0)

    def test_no_limit_files(self):
        b = cpu_budget(tempfile.mkdtemp())
        self.assertIsNone(b.quota)
        self.assertGreaterEqual(b.logical, 1)


class Checksums(unittest.TestCase):
    def test_checksum_is_order_and_value_sensitive(self):
        from threadwise.runners import checksum

        self.assertEqual(checksum([1, 2, 3]), checksum([1, 2, 3]))
        self.assertNotEqual(checksum([1, 2, 3]), checksum([3, 2, 1]))
        self.assertNotEqual(checksum([1, 2, 3]), checksum([1, 2, 4]))

    def test_all_modes_agree(self):
        """The whole tool is pointless if the modes compute different answers."""
        w = get("pure-python-cpu")
        report = run_benchmark(w, tasks=4, workers=2, repeat=1, warmup=0)
        self.assertTrue(report.consistent, [r.checksum for r in report.results])


class BenchmarkMath(unittest.TestCase):
    def _report(self) -> Report:
        return run_benchmark(get("io-latency"), tasks=8, workers=4, repeat=1, warmup=0)

    def test_speedup_of_serial_is_one(self):
        r = self._report()
        serial = next(x for x in r.results if x.mode == "serial")
        self.assertAlmostEqual(r.speedup(serial), 1.0, places=6)

    def test_speedup_is_never_nan_for_real_modes(self):
        r = self._report()
        for res in r.results:
            if not res.error:
                self.assertEqual(r.speedup(res), r.speedup(res))  # not NaN

    def test_io_speedup_exceeds_one(self):
        """8 sleeping tasks on 4 workers must beat running them one by one."""
        r = self._report()
        self.assertGreater(r.best_speedup, 2.0)

    def test_async_marked_unavailable_for_cpu(self):
        r = run_benchmark(get("pure-python-cpu"), tasks=2, workers=1, repeat=1, warmup=0)
        async_res = next(x for x in r.results if x.mode == "async")
        self.assertIsNotNone(async_res.error)

    def test_json_is_serialisable_and_self_consistent(self):
        r = self._report()
        payload = json.loads(r.to_json())
        self.assertEqual(payload["tool"], "threadwise")
        self.assertEqual(payload["version"], __version__)
        self.assertEqual(payload["config"]["tasks"], 8)
        self.assertTrue(payload["verdict"]["results_identical"])
        speeds = [x["speedup"] for x in payload["results"] if x["speedup"] is not None]
        self.assertIn(1.0, speeds)

    def test_single_core_yields_no_cpu_verdict(self):
        r = run_benchmark(get("pure-python-cpu"), tasks=2, workers=1, repeat=1, warmup=0)
        r.cpu = CpuBudget(logical=16, quota=1.0, source="cgroup v2")
        r.notes = []
        from threadwise.bench import _explain

        notes = _explain(r)
        self.assertTrue(any("1.00 CPU" in n for n in notes))
        text = render_table(r, Style(False))
        self.assertIn("no verdict", text)
        self.assertNotIn("✓ recommended", text)
        self.assertIsNone(json.loads(r.to_json())["verdict"]["recommended"])
        self.assertTrue(r.suppressed)


class Rendering(unittest.TestCase):
    def setUp(self):
        self.r = run_benchmark(get("io-latency"), tasks=8, workers=4, repeat=1, warmup=0)

    def test_table_contains_every_mode(self):
        text = render_table(self.r, Style(False))
        for mode in ("serial", "threads", "processes", "async"):
            self.assertIn(mode, text)
        self.assertNotIn("\033[", text)  # no ANSI when colour is off

    def test_markdown_has_table_and_verdict(self):
        md = render_markdown(self.r)
        self.assertIn("| mode |", md)
        self.assertIn("**Verdict:**", md)

    def test_colour_codes_only_when_asked(self):
        self.assertIn("\033[", render_table(self.r, Style(True)))


class Loader(unittest.TestCase):
    def _write(self, body: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".py")
        with os.fdopen(fd, "w") as fh:
            fh.write(body)
        self.addCleanup(os.unlink, path)
        return path

    def test_loads_run_function(self):
        w = load_script(self._write("def run(seed):\n    return seed * 2\n"))
        self.assertEqual(w.fn(21), 42)
        self.assertEqual(w.kind, "cpu")
        self.assertFalse(w.supports_async)

    def test_reads_declared_kind_and_async(self):
        w = load_script(
            self._write(
                'KIND = "io"\n'
                "async def arun(seed):\n    return seed\n"
                "def run(seed):\n    return seed\n"
            )
        )
        self.assertEqual(w.kind, "io")
        self.assertTrue(w.supports_async)

    def test_missing_run_is_a_clear_error(self):
        with self.assertRaises(LoadError) as ctx:
            load_script(self._write("x = 1\n"))
        self.assertIn("def run(seed)", str(ctx.exception))

    def test_missing_file_is_a_clear_error(self):
        with self.assertRaises(LoadError):
            load_script("/nope/does-not-exist.py")


class Cli(unittest.TestCase):
    def _run(self, argv, capsys=None):
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(argv)
        return code, buf.getvalue()

    def test_workloads_listing(self):
        code, out = self._run(["workloads"])
        self.assertEqual(code, 0)
        for name in WORKLOADS:
            self.assertIn(name, out)

    def test_modes_listing(self):
        code, out = self._run(["modes"])
        self.assertEqual(code, 0)
        self.assertIn("GIL", out)

    def test_bench_json(self):
        code, out = self._run(
            ["bench", "io-latency", "--json", "-n", "4", "-w", "2", "-r", "1", "--warmup", "0"]
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["workload"]["name"], "io-latency")

    def test_unknown_target_exits_2(self):
        import contextlib

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main(["bench", "no-such-workload"])
        self.assertEqual(code, 2)
        self.assertIn("not a built-in workload", err.getvalue())

    def test_unknown_mode_exits_2(self):
        import contextlib

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main(["bench", "io-latency", "--modes", "magic"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
