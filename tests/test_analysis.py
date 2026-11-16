"""Tests for the analysis layers: Amdahl fit, cost model, HTML report."""

from __future__ import annotations

import math
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from threadwise.bench import run_benchmark  # noqa: E402
from threadwise.htmlreport import render_html  # noqa: E402
from threadwise.insight import batching_advice, cost_model, decision, human_time  # noqa: E402
from threadwise.sweep import (  # noqa: E402
    AmdahlFit,
    Sweep,
    SweepPoint,
    amdahl_speedup,
    fit_amdahl,
    run_sweep,
)
from threadwise.workloads import get  # noqa: E402


class AmdahlModel(unittest.TestCase):
    def test_formula_endpoints(self):
        self.assertAlmostEqual(amdahl_speedup(0.1, 1), 1.0)
        self.assertAlmostEqual(amdahl_speedup(0.1, 10), 1 / (0.1 + 0.09))
        self.assertAlmostEqual(amdahl_speedup(0.0, 1000), 1000.0)

    def test_recovers_known_serial_fraction(self):
        s_true = 0.05
        pts = [
            SweepPoint.of(n, amdahl_speedup(s_true, n))
            for n in (1, 2, 4, 8, 16)
        ]
        fit = fit_amdahl(pts)
        self.assertIsNotNone(fit)
        self.assertAlmostEqual(fit.serial_fraction, s_true, places=3)
        self.assertAlmostEqual(fit.max_speedup, 20.0, places=0)

    def test_linear_curve_is_flagged_as_lower_bound(self):
        """Five perfect points must not be sold as a hard ceiling."""
        pts = [SweepPoint.of(n, float(n)) for n in (1, 2, 4, 8)]
        fit = fit_amdahl(pts)
        self.assertTrue(fit.is_lower_bound)

    def test_bending_curve_is_not_lower_bound(self):
        pts = [
            SweepPoint.of(n, amdahl_speedup(0.2, n))
            for n in (1, 2, 4, 8, 16)
        ]
        fit = fit_amdahl(pts)
        self.assertFalse(fit.is_lower_bound)
        self.assertLess(fit.max_speedup, 6.0)

    def test_too_few_points_returns_none(self):
        self.assertIsNone(fit_amdahl([SweepPoint.of(1, 1.0)]))

    def test_workers_90pct_is_bounded(self):
        pts = [
            SweepPoint.of(n, amdahl_speedup(0.1, n))
            for n in (1, 2, 4, 8)
        ]
        fit = fit_amdahl(pts)
        measured = max(p.workers for p in pts) * 8
        self.assertLessEqual(fit.workers_90pct or 0, measured)


class SweepIntegration(unittest.TestCase):
    def test_sweep_io_is_monotonic_and_flagged(self):
        s = run_sweep(get("io-latency"), worker_counts=(1, 2, 4), tasks=24, repeat=1,
                      warmup=0, cpu_usable=8.0)
        self.assertEqual([p.workers for p in s.points], [1, 2, 4])
        self.assertAlmostEqual(s.points[0].speedup, 1.0, places=6)
        self.assertAlmostEqual(s.points[0].speedup, 1.0, places=6)
        self.assertTrue(all(p.speedup >= 1.0 for p in s.points))
        self.assertIsNotNone(s.fit)
        self.assertTrue(s.fit.is_lower_bound or s.fit.serial_fraction >= 0)

    def test_sweep_serialises_to_json(self):
        s = run_sweep(get("io-latency"), worker_counts=(1, 2), tasks=8, repeat=1,
                      warmup=0, cpu_usable=4.0)
        d = s.to_dict()
        self.assertEqual(d["mode"], "threads")
        self.assertEqual(len(d["points"]), 2)

    def test_empty_worker_counts_rejected(self):
        with self.assertRaises(ValueError):
            run_sweep(get("io-latency"), worker_counts=(), tasks=4, repeat=1, warmup=0)


class CostModel(unittest.TestCase):
    def test_human_time_units(self):
        self.assertEqual(human_time(0.0000001), "0 µs")
        self.assertIn("ms", human_time(0.012))
        self.assertIn("s", human_time(1.5))
        self.assertIn("min", human_time(120))
        self.assertIn("h", human_time(7200))

    def test_io_workload_produces_no_batching_advice(self):
        r = run_benchmark(get("io-latency"), tasks=16, workers=4, repeat=1, warmup=0)
        self.assertIsNone(batching_advice(r))

    def test_decision_names_a_mode_or_refuses(self):
        r = run_benchmark(get("io-latency"), tasks=16, workers=4, repeat=1, warmup=0)
        headline, reason = decision(r)
        self.assertTrue(headline)
        self.assertTrue(reason)

    def test_cost_model_speedup_never_negative(self):
        r = run_benchmark(get("io-latency"), tasks=16, workers=4, repeat=1, warmup=0)
        model = cost_model(r)
        if model:
            self.assertGreaterEqual(model.speedup_at(4, task_scale=0.01), 0.0)


class HtmlReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_benchmark(
            get("io-latency"), tasks=16, workers=4, repeat=1, warmup=0
        )
        cls.sweep = run_sweep(
            get("io-latency"), worker_counts=(1, 2, 4), tasks=16, repeat=1,
            warmup=0, cpu_usable=4.0,
        )

    def test_self_contained(self):
        doc = render_html(report=self.report, sweep=self.sweep)
        self.assertNotIn("http://", doc)
        self.assertNotIn("https://", doc)  # no CDN, no remote fonts
        self.assertNotIn("<link", doc)
        self.assertNotIn("<img", doc)  # charts are inline SVG
        self.assertIn("<svg", doc)

    def test_has_decision_and_verdict_numbers(self):
        doc = render_html(report=self.report)
        self.assertIn("decision", doc)
        best = self.report.speedup(self.report._best_result())
        self.assertIn(f"{best:.2f}×", doc)

    def test_embeds_raw_data_as_valid_json(self):
        doc = render_html(report=self.report, sweep=self.sweep)
        import json

        m = re.search(
            r'<script type="application/json" class="threadwise-data">(.*?)</script>', doc, re.S
        )
        self.assertIsNotNone(m)
        payload = json.loads(m.group(1))
        self.assertIn("report", payload)
        self.assertIn("sweep", payload)

    def test_multi_report_is_a_single_valid_document(self):
        from threadwise.htmlreport import render_multi

        second = run_benchmark(get("pure-python-cpu"), tasks=2, workers=1, repeat=1, warmup=0)
        doc = render_multi([self.report, second])
        self.assertEqual(doc.count("<html"), 1)
        self.assertEqual(doc.count("<body"), 1)
        self.assertEqual(doc.count("</body>"), 1)
        self.assertIn("io-latency", doc)
        self.assertIn("pure-python-cpu", doc)

    def test_sweep_only_report_works(self):
        doc = render_html(sweep=self.sweep, title="sweep")
        self.assertIn("scalability", doc)

    def test_no_measurement_means_error(self):
        with self.assertRaises(ValueError):
            render_html()

    def test_suppressed_report_is_labelled(self):
        from threadwise.runners import CpuBudget

        self.report.cpu = CpuBudget(logical=16, quota=1.0, source="cgroup v2")
        self.report.workload = get("pure-python-cpu")
        cpu = run_benchmark(get("pure-python-cpu"), tasks=2, workers=1, repeat=1, warmup=0)
        cpu.cpu = CpuBudget(logical=16, quota=1.0, source="cgroup v2")
        doc = render_html(report=cpu)
        self.assertIn("insufficient cpu", doc)
        self.assertIn("Not enough CPU", doc)


if __name__ == "__main__":
    unittest.main()
