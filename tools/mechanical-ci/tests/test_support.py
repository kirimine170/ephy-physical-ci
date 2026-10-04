"""Original synthetic fixtures only; no printer or product geometry."""
import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from physical_ci.cli import main, write_json
from physical_ci.errors import InputError
from physical_ci.gcode import extract
from physical_ci.manifest import sha256
from physical_ci.support import clip_interval, load_regions, screen_support

REGION = {"id": "protected", "min_mm": [0, 0, 0], "max_mm": [1, 1, 1]}
HEADER = "G21\nG90\nM83\nG1 X-1 Y0.5 Z0.5\n;TYPE:Support material\n;WIDTH:0.4\n;HEIGHT:0.2\n"
GCODE = HEADER + "G1 X2 E1\n"


def screen(text):
    stationary = []
    summary, segments = extract(text, stationary_events=stationary)
    return screen_support(summary, segments, stationary, [REGION])


class ClipTests(unittest.TestCase):
    def test_analytic_crossing_both_endpoints_outside(self):
        interval = clip_interval([-1, .5, .5], [2, .5, .5], REGION, .4, .2)
        for actual, expected in zip(interval, [.8 / 3, 2.2 / 3]):
            self.assertAlmostEqual(actual, expected, places=15)

    def test_parallel_contact_and_separation_in_y_and_z(self):
        for axis in (1, 2):
            for value, expected_hit in ((1.2, True), (1.21, False), (-.2, True), (-.21, False)):
                with self.subTest(axis=axis, value=value):
                    start, end = [-1, .5, .5], [2, .5, .5]
                    start[axis] = end[axis] = value
                    result = clip_interval(start, end, REGION, .4, .2)
                    self.assertEqual(result is not None, expected_hit)

    def test_reversed_direction_clip_parameters(self):
        forward = clip_interval([-1, .5, .5], [3, .5, .5], REGION, .4, .2)
        reverse = clip_interval([3, .5, .5], [-1, .5, .5], REGION, .4, .2)
        self.assertAlmostEqual(forward[0], .2)
        self.assertAlmostEqual(forward[1], .55)
        self.assertAlmostEqual(reverse[0], .45)
        self.assertAlmostEqual(reverse[1], .8)

    def test_diagonal_bbox_overlap_is_not_a_hit(self):
        self.assertIsNone(clip_interval([-1, .5, .5], [.5, 2, .5], REGION, .4, .2))

    def test_single_point_tangent(self):
        interval = clip_interval([-1, .4, .5], [.4, 1.8, .5], REGION, .4, .2)
        self.assertIsNotNone(interval)
        self.assertAlmostEqual(interval[0], 4 / 7)
        self.assertAlmostEqual(interval[1], 4 / 7)
        self.assertIsNone(clip_interval([-1, .4, .5], [.4, 1.800000000000001, .5], REGION, .4, .2))

    def test_point_envelope_inside_outside(self):
        self.assertEqual(clip_interval([.5, .5, .5], [.5, .5, .5], REGION, .4, .2), [0, 1])
        self.assertIsNone(clip_interval([2, 2, 2], [2, 2, 2], REGION, .4, .2))

    def test_arithmetic_overflow_is_an_input_error(self):
        cases = [([-1e308, 0, 0], [1e308, 0, 0], REGION, .4, .2),
                 ([0, 0, 0], [1, 0, 0], {"min_mm": [1e308, 0, 0], "max_mm": [1.5e308, 1, 1]}, 1.5e308, .2),
                 ([-1e308, 0, 0], [-1e308 + 1e292, 0, 0],
                  {"min_mm": [1e308, 0, 0], "max_mm": [1.5e308, 1, 1]}, .4, .2)]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(InputError):
                clip_interval(*args)


class ScreenTests(unittest.TestCase):
    def test_support_interface_hits_and_perimeter_exclusion(self):
        text = GCODE + ";TYPE:Support material interface\nG1 X-1 E1\n;TYPE:Perimeter\nG1 X2 E1\n"
        result = screen(text)
        self.assertEqual([hit["role"] for hit in result["observed_hits"]],
                         ["Support material", "Support material interface"])
        self.assertEqual([hit["line"] for hit in result["observed_hits"]], [8, 10])
        self.assertEqual(result["observed_hits"][0]["roi_id"], "protected")
        self.assertTrue(result["coverage_complete"])
        self.assertEqual(result["proxy"], "axis_aligned_envelope_proxy")
        self.assertEqual(result["support_removal"], "not_implemented")
        self.assertEqual(result["physical_validation"], "not_performed")
        self.assertFalse(result["printer_ready"])

    def test_known_perimeter_and_support_miss_are_complete_nominal_screens(self):
        for text in (GCODE.replace("Support material", "Perimeter"), GCODE.replace("Y0.5", "Y1.21")):
            with self.subTest(text=text):
                result = screen(text)
                self.assertEqual(result["observed_hits"], [])
                self.assertTrue(result["coverage_complete"])
                self.assertEqual(result["outcome"], "no_candidate_observed")

    def test_unknown_roles_do_not_prove_negative(self):
        for role in ("Unknown", "Custom", "Future support", "support material", ""):
            with self.subTest(role=role):
                result = screen(GCODE.replace("Support material", role))
                self.assertFalse(result["coverage_complete"])
                self.assertEqual(result["outcome"], "unknown")
                self.assertIn("unknown_role", result["coverage_gaps"][0]["reasons"])

    def test_missing_and_unknown_dimension_metadata(self):
        for text in (GCODE.replace(";WIDTH:0.4\n", ""), GCODE.replace(";HEIGHT:0.2\n", ""),
                     GCODE.replace(";WIDTH:0.4", ";FUTURE_WIDTH:0.4")):
            with self.subTest(text=text):
                result = screen(text)
                self.assertFalse(result["coverage_complete"])
                self.assertIn("missing_dimensions", result["coverage_gaps"][0]["reasons"])

    def test_nonplanar_deposition_gap_for_support_and_perimeter(self):
        for role in ("Support material", "Perimeter"):
            with self.subTest(role=role):
                result = screen(GCODE.replace("Support material", role).replace("X2 E1", "X2 Z0.6 E1"))
                self.assertFalse(result["coverage_complete"])
                self.assertEqual(result["observed_hits"], [])
                self.assertIn("nonplanar_deposition", result["coverage_gaps"][0]["reasons"])

    def test_hits_and_incomplete_coverage_coexist(self):
        result = screen(GCODE + ";TYPE:Future support\nG1 X3 E1\n")
        self.assertEqual(len(result["observed_hits"]), 1)
        self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["outcome"], "candidate_found")

    def test_known_stationary_support_prime_uses_point_envelope(self):
        for prime in ("G1 E1", "G1 X0.5 E1"):
            with self.subTest(prime=prime):
                text = HEADER.replace("X-1", "X0.5") + prime + "\n"
                result = screen(text)
                self.assertEqual(result["extrusion_segments"], 0)
                self.assertEqual(result["observed_hits"][0]["kind"], "stationary_prime")
                self.assertEqual(result["observed_hits"][0]["clip_interval"], [0, 1])
                self.assertTrue(result["coverage_complete"])
                with self.assertRaises(InputError):
                    extract(text)  # Preserve analyze-gcode's moving-path requirement.

    def test_unknown_stationary_prime_position_role_or_dimensions(self):
        cases = [(HEADER.replace("G1 X-1 Y0.5 Z0.5\n", "") + "G1 E1\n", "unknown_stationary_position"),
                 (HEADER.replace(";TYPE:Support material\n", "") + "G1 E1\n", "unknown_role"),
                 (HEADER.replace(";WIDTH:0.4\n", "") + "G1 E1\n", "missing_dimensions")]
        for text, reason in cases:
            with self.subTest(reason=reason):
                result = screen(text)
                self.assertFalse(result["coverage_complete"])
                self.assertIn(reason, result["coverage_gaps"][0]["reasons"])

    def test_unknown_prime_cannot_hide_behind_perimeter(self):
        text = "G21\nG90\nM83\nG1 E1\n" + GCODE
        result = screen(text)
        self.assertFalse(result["coverage_complete"])
        self.assertEqual(len(result["observed_hits"]), 1)

    def test_retract_recovery_is_not_stationary_deposition(self):
        result = screen(HEADER + "G1 E-1\nG1 E1\nG1 X2 E1\n")
        self.assertEqual(result["stationary_extrusion_mm"], 0)
        self.assertEqual(len(result["observed_hits"]), 1)
        self.assertTrue(result["coverage_complete"])

    def test_mixed_retract_clip_starts_at_deposition(self):
        result = screen(HEADER + "G1 E-1\nG1 X2 E2\n")
        hit = result["observed_hits"][0]
        self.assertEqual(hit["from_mm"], [.5, .5, .5])
        self.assertEqual(hit["clip_interval"][0], 0)
        self.assertAlmostEqual(hit["clip_interval"][1], .7 / 1.5)

    def test_intersection_work_limit(self):
        with patch("physical_ci.support.MAX_INTERSECTION_CHECKS", 0), self.assertRaises(InputError):
            screen(GCODE)

    def test_tiny_positive_extrusion_and_tiny_motion_are_preserved(self):
        result = screen(GCODE.replace("E1", "E0.0000000001"))
        self.assertEqual(len(result["observed_hits"]), 1)
        stationary = []
        text = "G21\nG90\nM83\nG1 X0 Y0 Z0\n;TYPE:Support material\n;WIDTH:0.0000000001\n;HEIGHT:0.0000000001\nG1 X0.0000000008 E1\n"
        summary, segments = extract(text, stationary_events=stationary)
        region = {"id": "tiny", "min_mm": [1.5e-10, -1e-10, -1e-10], "max_mm": [2.5e-10, 1e-10, 1e-10]}
        result = screen_support(summary, segments, stationary, [region])
        self.assertEqual(len(result["observed_hits"]), 1)
        self.assertEqual(result["observed_hits"][0]["kind"], "moving_extrusion")

    def test_metadata_whitespace_is_read_and_ambiguous_forms_rejected(self):
        result = screen(GCODE.replace(";TYPE:Support material", ";TYPE:Perimeter\n ;TYPE:Support material"))
        self.assertEqual(len(result["observed_hits"]), 1)
        for metadata in (";type:Support material", ";TYPE :Support material", "G1 X0 ;TYPE:Support material"):
            with self.subTest(metadata=metadata), self.assertRaises(InputError):
                screen(GCODE.replace(";TYPE:Support material", metadata))

    def test_stationary_retract_and_length_accumulation_overflow(self):
        huge = "1" + "0" * 308
        cases = [HEADER + f"G1 E{huge}\nG1 E{huge}\n",
                 GCODE + f"G1 E-{huge}\nG1 E-{huge}\n",
                 HEADER + f"G1 X{huge} E1\nG1 X0 E1\n"]
        for text in cases:
            with self.subTest(text=text), self.assertRaises(InputError):
                screen(text)


class RoiAndCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.gcode, self.roi, self.output = (self.root / name for name in ("synthetic.gcode", "roi.json", "report.json"))
        self.gcode.write_text(GCODE, encoding="utf-8")
        self.digest = sha256(self.gcode)
        self.data = {"schema_version": 1, "frame": "gcode_machine_coordinates", "units": "mm",
                     "gcode_sha256": self.digest, "regions": [copy.deepcopy(REGION)]}

    def tearDown(self):
        self.directory.cleanup()

    def write(self):
        self.roi.write_text(json.dumps(self.data), encoding="utf-8")
        return self.roi

    def quiet(self, output=None):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main(["screen-support", str(self.gcode), "--roi", str(self.roi),
                         "--output", str(output or self.output)])

    def test_cli_hashes_oracle_and_byte_determinism(self):
        self.write()
        self.assertEqual(self.quiet(), 0)
        other = self.root / "report-2.json"
        self.assertEqual(self.quiet(other), 0)
        self.assertEqual(self.output.read_bytes(), other.read_bytes())
        result = json.loads(self.output.read_text())
        self.assertEqual(result["gcode_sha256"], self.digest)
        self.assertEqual(result["roi_sha256"], sha256(self.roi))
        self.assertAlmostEqual(result["observed_hits"][0]["clip_interval"][0], .8 / 3)
        self.assertTrue(result["coverage_complete"])

    def test_cli_incomplete_negative_is_explicit(self):
        self.gcode.write_text(GCODE.replace("Support material", "Future role"))
        self.data["gcode_sha256"] = sha256(self.gcode)
        self.write()
        self.assertEqual(self.quiet(), 0)
        result = json.loads(self.output.read_text())
        self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["outcome"], "unknown")

    def test_bad_schema_frames_units_hashes_and_unknown_keys(self):
        cases = [("schema_version", True), ("schema_version", 1.0), ("schema_version", 2),
                 ("frame", "assembly"), ("frame", "print"), ("units", "inch"),
                 ("assembly_to_print", [[1, 0, 0, 0]] * 4), ("gcode_sha256", "f" * 64),
                 ("gcode_sha256", "A" * 64), ("gcode_sha256", True), ("gcode_sha256", "short")]
        original = copy.deepcopy(self.data)
        for key, value in cases:
            with self.subTest(key=key, value=value):
                self.data = copy.deepcopy(original)
                self.data[key] = value
                self.assertEqual(self.quiet_after_write(), 2)
                self.assertFalse(self.output.exists())

    def quiet_after_write(self):
        self.write()
        return self.quiet()

    def test_missing_fields_and_nonobjects(self):
        original = copy.deepcopy(self.data)
        for key in original:
            with self.subTest(key=key):
                self.data = copy.deepcopy(original)
                del self.data[key]
                with self.assertRaises(InputError):
                    load_regions(self.write(), self.digest)
        for raw in ("[]", "null", "1", '{"schema_version":'):
            self.roi.write_text(raw)
            with self.assertRaises(InputError):
                load_regions(self.roi, self.digest)

    def test_regions_and_unique_identifiers(self):
        for regions in ([], None, {}, [REGION] * 1001, [REGION, REGION]):
            with self.subTest(regions_type=type(regions), count=len(regions) if regions else 0):
                self.data["regions"] = regions
                with self.assertRaises(InputError):
                    load_regions(self.write(), self.digest)
        for identifier in (None, True, 1, "", " ", "x" * 201):
            self.data["regions"] = [dict(REGION, id=identifier)]
            with self.subTest(identifier=identifier), self.assertRaises(InputError):
                load_regions(self.write(), self.digest)

    def test_invalid_vectors_bounds_and_nonboolean_numbers(self):
        for lower in (True, None, [], [0, 0], [0, 0, 0, 0], [False, 0, 0],
                      ["0", 0, 0], [1, 0, 0], [2, 0, 0], [float("nan"), 0, 0],
                      [float("inf"), 0, 0], [10 ** 400, 0, 0]):
            self.data["regions"] = [dict(REGION, min_mm=lower)]
            with self.subTest(lower=lower), self.assertRaises(InputError):
                load_regions(self.write(), self.digest)
        self.data["regions"] = [dict(REGION, mystery=1)]
        with self.assertRaises(InputError):
            load_regions(self.write(), self.digest)

    def test_duplicate_json_keys_top_level_and_nested(self):
        raw = json.dumps(self.data)
        for bad in (raw.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'),
                    raw.replace('"id": "protected"', '"id": "protected", "id": "other"'),
                    raw.replace('"id": "protected"', '"id": "protected", "\\u0069d": "other"')):
            self.roi.write_text(bad)
            with self.assertRaisesRegex(InputError, "duplicate ROI JSON key"):
                load_regions(self.roi, self.digest)

    def test_overflow_utf8_recursion_and_file_limits(self):
        raw = json.dumps(self.data)
        for bad in (raw.replace('"min_mm": [0, 0, 0]', '"min_mm": [1e309, 0, 0]'),
                    "[" * 2000 + "]" * 2000, " " * (1024 * 1024 + 1)):
            self.roi.write_text(bad)
            with self.assertRaises(InputError):
                load_regions(self.roi, self.digest)
        self.roi.write_bytes(b"\xff")
        with self.assertRaises(InputError):
            load_regions(self.roi, self.digest)
        self.write()
        with self.gcode.open("wb") as stream:
            stream.truncate(64 * 1024 * 1024 + 1)
        self.assertEqual(self.quiet(), 2)
        self.assertFalse(self.output.exists())

    def test_gcode_hash_tamper_and_invalid_gcode_do_not_write(self):
        self.write()
        self.gcode.write_text(GCODE + ";tampered\n")
        self.assertEqual(self.quiet(), 2)
        self.assertFalse(self.output.exists())
        self.gcode.write_text(GCODE + "G2 X2 E1\n")
        self.data["gcode_sha256"] = sha256(self.gcode)
        self.write()
        self.assertEqual(self.quiet(), 2)
        self.assertFalse(self.output.exists())

    def test_output_inputs_existing_and_hardlink_are_preserved(self):
        self.write()
        gcode_before, roi_before = self.gcode.read_bytes(), self.roi.read_bytes()
        for target in (self.gcode, self.roi):
            self.assertEqual(self.quiet(target), 2)
        self.output.write_text("preserve")
        self.assertEqual(self.quiet(), 2)
        self.assertEqual(self.output.read_text(), "preserve")
        link = self.root / "linked.json"
        os.link(self.gcode, link)
        self.assertEqual(self.quiet(link), 2)
        self.assertEqual(self.gcode.read_bytes(), gcode_before)
        self.assertEqual(self.roi.read_bytes(), roi_before)

    def test_modified_inputs_during_read_fail_closed(self):
        self.write()
        with patch("physical_ci.cli.sha256", side_effect=[self.digest, "f" * 64]):
            self.assertEqual(self.quiet(), 2)
        self.assertFalse(self.output.exists())
        with patch("physical_ci.support.sha256", return_value="f" * 64), self.assertRaises(InputError):
            load_regions(self.roi, self.digest)

    def test_nonfinite_json_is_rejected_before_creating_output(self):
        with self.assertRaises(InputError):
            write_json(self.output, {"invalid": float("inf")})
        self.assertFalse(self.output.exists())

    def test_stationary_overflow_does_not_create_output(self):
        huge = "1" + "0" * 308
        self.gcode.write_text(HEADER + f"G1 E{huge}\nG1 E{huge}\n")
        self.data["gcode_sha256"] = sha256(self.gcode)
        self.write()
        self.assertEqual(self.quiet(), 2)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
