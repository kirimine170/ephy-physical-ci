"""Synthetic exact-E bookkeeping regressions; no product geometry or printer data."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from physical_ci.cli import main
from physical_ci.errors import InputError
from physical_ci.gcode import MAX_E_TOKEN_CHARS, extract
from physical_ci.support import screen_support

HEADER = "G21\nG90\nM82\nG92 E0\nG1 X0 Y0 Z0\n;TYPE:Support material\n;WIDTH:0.4\n;HEIGHT:0.2\n"
RESTORE = "G92 E2.3\nG1 E0.3\nG92 E0\nG1 E2\n"
MODEL = ";TYPE:Perimeter\nG1 X10 E3\n"
ROI = {"id": "origin", "min_mm": [-.1, -.1, -.1], "max_mm": [.1, .1, .1]}


class ExactExtrusionTests(unittest.TestCase):
    def test_decimal_absolute_retract_restore_has_no_phantom_prime(self):
        stationary = []
        summary, paths = extract(HEADER + RESTORE + MODEL, stationary_events=stationary)
        self.assertEqual(stationary, [])
        self.assertEqual(summary["stationary_extrusion_mm"], 0)
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0]["filament_delta_mm"], 1)

    def test_phantom_prime_does_not_create_support_hit(self):
        stationary = []
        summary, paths = extract(HEADER + RESTORE + MODEL, stationary_events=stationary)
        report = screen_support(summary, paths, stationary, [ROI])
        self.assertEqual(report["observed_hits"], [])
        self.assertEqual(report["screened_support_events"], 0)
        self.assertTrue(report["coverage_complete"])

    def test_real_sub_ulp_prime_is_retained_and_screened(self):
        stationary = []
        text = HEADER + RESTORE + "G1 E2.0000000000000001\n" + MODEL
        summary, paths = extract(text, stationary_events=stationary)
        self.assertEqual(len(stationary), 1)
        self.assertEqual(stationary[0]["filament_delta_mm"], 1e-16)
        self.assertEqual(summary["stationary_extrusion_mm"], 1e-16)
        report = screen_support(summary, paths, stationary, [ROI])
        self.assertEqual(len(report["observed_hits"]), 1)
        self.assertEqual(report["observed_hits"][0]["kind"], "stationary_prime")

    def test_small_moving_increment_after_large_absolute_baseline(self):
        _, paths = extract(HEADER + "G92 E10000000000000000\nG1 X1 E10000000000000001\n")
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0]["filament_delta_mm"], 1)

    def test_relative_decimal_debt_is_exact_across_g92(self):
        stationary = []
        text = HEADER + "M83\nG1 E-0.1\nG1 E-0.2\nG92 E100\nG1 E0.3\nG1 X1 E0.2\n"
        summary, paths = extract(text, stationary_events=stationary)
        self.assertEqual(stationary, [])
        self.assertEqual(summary["stationary_extrusion_mm"], 0)
        self.assertEqual(paths[0]["filament_delta_mm"], .2)

    def test_mixed_move_ratio_is_derived_from_exact_debt(self):
        text = HEADER + "M83\nG1 E-0.1\nG1 E-0.2\nG1 X2 E0.6\n"
        _, paths = extract(text)
        self.assertEqual(paths[0]["from_mm"], [1, 0, 0])
        self.assertEqual(paths[0]["filament_delta_mm"], .3)

    def test_switching_modes_retains_exact_e_baseline(self):
        text = HEADER + "G92 E10000000000000000\nM83\nG1 X1 E0.1\nG1 X2 E0.2\nM82\nG1 X3 E10000000000000000.4\n"
        _, paths = extract(text)
        self.assertEqual([p["filament_delta_mm"] for p in paths], [.1, .2, .1])

    def test_representable_subnormal_extrusion_is_not_suppressed(self):
        tiny = "0." + "0" * 322 + "1"
        _, paths = extract(HEADER + "M83\nG1 X1 E" + tiny + "\n")
        self.assertEqual(len(paths), 1)
        self.assertGreater(paths[0]["filament_delta_mm"], 0)

    def test_unrepresentable_nonzero_report_is_rejected(self):
        tiny = "0." + "0" * 399 + "1"
        for command in ("G1 X1 E", "G1 E"):
            with self.subTest(command=command), self.assertRaisesRegex(InputError, "below float report precision"):
                extract(HEADER + "M83\n" + command + tiny + "\nG1 X2 E1\n")

    def test_tiny_exact_retraction_can_cancel_without_a_report(self):
        tiny = "0." + "0" * 399 + "1"
        stationary = []
        _, paths = extract(HEADER + f"M83\nG1 E-{tiny}\nG1 E{tiny}\nG1 X1 E1\n", stationary_events=stationary)
        self.assertEqual(stationary, [])
        self.assertEqual(paths[0]["filament_delta_mm"], 1)

    def test_mixed_extrusion_that_collapses_to_endpoint_is_rejected(self):
        with self.assertRaisesRegex(InputError, "coordinate report precision"):
            extract(HEADER + "M83\nG1 E-2\nG1 X1 E2.00000000000000000001\n")

    def test_e_token_resource_bound(self):
        for token in ("0." + "0" * MAX_E_TOKEN_CHARS, "0" * MAX_E_TOKEN_CHARS + "1"):
            with self.subTest(length=len(token)), self.assertRaisesRegex(InputError, "E token exceeds"):
                extract(HEADER + "M83\nG1 X1 E" + token + "\n")

    def test_stationary_sum_converts_only_at_report_boundary(self):
        summary, paths = extract(HEADER + "M83\nG1 E0.1\nG1 E0.2\nG1 X1 E1\n")
        self.assertEqual(summary["stationary_extrusion_mm"], .3)
        self.assertEqual(paths[0]["filament_delta_mm"], 1)

    def test_underflow_cli_fails_without_success_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "tiny.gcode"
            source.write_text(HEADER + "M83\nG1 X1 E0." + "0" * 399 + "1\nG1 X2 E1\n")
            output, segments = root / "summary.json", root / "segments.jsonl"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                status = main(["analyze-gcode", str(source), "--output", str(output), "--segments", str(segments)])
            self.assertEqual(status, 2)
            self.assertFalse(output.exists())
            self.assertFalse(segments.exists())


if __name__ == "__main__":
    unittest.main()
