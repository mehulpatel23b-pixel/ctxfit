import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ctxfit.catalog import (MODELS, cost_usd, fits, resolve, trim_plan)
from ctxfit.cli import run
from ctxfit.estimator import (collect, estimate_file, estimate_tokens,
                              kind_for, looks_binary)


class TestEstimator(unittest.TestCase):
    def test_empty_text_is_zero(self):
        self.assertEqual(estimate_tokens(""), 0)

    def test_nonzero_for_short_text(self):
        self.assertGreaterEqual(estimate_tokens("print('hi')"), 1)

    def test_prose_longer_than_code_ratio(self):
        code = "x=1;" * 1000
        prose = "word " * 1000
        # same char count, but dense code should estimate >= prose tokens
        self.assertGreaterEqual(estimate_tokens(code, "code"),
                                estimate_tokens(prose[: len(code)], "prose"))
        self.assertGreater(estimate_tokens(prose, "prose"), 0)

    def test_kind_classification(self):
        self.assertEqual(kind_for("a.py"), "code")
        self.assertEqual(kind_for("a.json"), "data")
        self.assertEqual(kind_for("a.md"), "prose")
        self.assertEqual(kind_for("a.unknownext"), "default")

    def test_binary_detected(self):
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as fh:
            fh.write(b"\x00\x01\x02binary")
            path = fh.name
        self.addCleanup(os.remove, path)
        self.assertTrue(looks_binary(path))

    def test_estimate_file_tracks_metadata(self):
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                         encoding="utf-8") as fh:
            fh.write("print('hello')\n")
            path = fh.name
        self.addCleanup(os.remove, path)
        est = estimate_file(path)
        self.assertEqual(est["lines"], 2)
        self.assertEqual(est["kind"], "code")
        self.assertGreater(est["tokens"], 0)

    def test_collect_sorts_desc_and_skips_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "node_modules"))
            with open(os.path.join(tmp, "a.py"), "w") as fh:
                fh.write("a" * 4000)
            with open(os.path.join(tmp, "node_modules", "b.py"), "w") as fh:
                fh.write("b" * 4000)
            files, skipped = collect([tmp])
            self.assertEqual([f["path"].endswith("a.py") for f in files], [True])
            self.assertEqual(skipped, [])


class TestCatalog(unittest.TestCase):
    def test_all_windows_positive(self):
        for name, (window, _) in MODELS.items():
            self.assertGreater(window, 0, name)

    def test_resolve_overrides_budget(self):
        self.assertEqual(resolve("mystery", 50000)[1], 50000)

    def test_resolve_unknown_without_budget_raises(self):
        with self.assertRaises(KeyError):
            resolve("mystery-model")

    def test_fits_verdicts(self):
        v = fits(10_000, 6_000, reserve_out=1000)
        self.assertEqual((v["status"], v["free"]), ("FITS", 3_000))
        v = fits(10_000, 100_000, reserve_out=1000)
        self.assertEqual((v["status"], v["over_by"]), ("OVER", 91_000))

    def test_fits_usage_pct(self):
        self.assertAlmostEqual(fits(101_000, 100_000, 1000)["usage_pct"], 100.0)

    def test_cost(self):
        self.assertAlmostEqual(cost_usd(1_000_000, 2.0), 2.0)
        self.assertAlmostEqual(cost_usd(500_000, 2.0), 1.0)
        self.assertIsNone(cost_usd(100, None))

    def test_trim_plan_already_fits(self):
        self.assertEqual(trim_plan([{"tokens": 10, "path": "x"}], 10_000), [])

    def test_trim_plan_greedy(self):
        files = [{"tokens": 60, "path": "b"}, {"tokens": 55, "path": "a"},
                 {"tokens": 5, "path": "c"}]
        # total 120 vs budget 100: dropping 'b' (60) leaves 60 -> fits
        plan = trim_plan(files, 100, reserve_out=0)
        self.assertEqual([d["path"] for d in plan], ["b"])
        self.assertEqual(plan[-1]["remaining"], 60)
        # budget 50: after dropping b (60 left) still over, drop a too (5 left)
        plan = trim_plan(files, 50, reserve_out=0)
        self.assertEqual([d["path"] for d in plan], ["b", "a"])
        self.assertEqual(plan[-1]["remaining"], 5)


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name
        with open(os.path.join(self.dir, "small.py"), "w") as fh:
            fh.write("x = 1\n" * 200)

    def _run(self, *args):
        return run([os.path.join(self.dir, "small.py"), *args])

    def test_exit_zero_when_fits(self):
        self.assertEqual(self._run("--model", "gpt-5"), 0)

    def test_exit_one_when_over(self):
        with open(os.path.join(self.dir, "huge.md"), "w") as fh:
            fh.write("word " * 400_000)
        rc = run([os.path.join(self.dir, "huge.md"), "--model", "llama-3.3-70b"])
        self.assertEqual(rc, 1)

    def test_exit_64_unknown_model(self):
        self.assertEqual(run([self.dir, "--model", "nope-9000"]), 64)

    def test_json_output_and_compare(self):
        proc = subprocess.run(
            [sys.executable, "-m", "ctxfit.cli", os.path.join(self.dir),
             "--json", "--compare"],
            capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": os.path.join(os.path.dirname(__file__), "..", "src")})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIn("fit", payload)
        self.assertTrue(len(payload["matrix"]) >= 10)
        row = payload["matrix"][0]
        for key in ("model", "budget", "status", "usage_pct", "cost_usd"):
            self.assertIn(key, row)


if __name__ == "__main__":
    unittest.main()
