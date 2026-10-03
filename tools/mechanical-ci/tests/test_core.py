import contextlib
import copy
import importlib.util
import io
import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from physical_ci.cli import main
from physical_ci.errors import InputError
from physical_ci.gcode import extract
from physical_ci.geometry import check_path, sampled_positions
from physical_ci.manifest import load_manifest
from physical_ci.slicer import inspect_profile

HEADER = "G21\nG90\nM82\nG92 E0\nG1 X0 Y0 Z0\n;TYPE:Perimeter\n;WIDTH:0.4\n;HEIGHT:0.2\n;Z:0.2\n"


class ToolpathTests(unittest.TestCase):
    def test_absolute_extrusion_and_metadata(self):
        summary, paths = extract(HEADER + "G1 X1 E1\nG1 Y1 E2\n")
        self.assertEqual(summary["extrusion_segments"], 2)
        self.assertEqual(paths[1]["from_mm"], [1,0,0])
        self.assertEqual(paths[1]["to_mm"], [1,1,0])
        self.assertEqual(summary["width_range_mm"], [.4,.4])
        self.assertEqual(summary["physical_validation"], "not_performed")

    def test_relative_extrusion_and_g92(self):
        _, paths = extract(HEADER + "M83\nG1 X1 E1\nG92 E0\nG1 X2 E0.5\n")
        self.assertEqual([p["filament_delta_mm"] for p in paths], [1,.5])

    def test_retract_restore_is_not_deposition(self):
        _, paths = extract(HEADER + "G1 E-2\nG92 E0\nG1 X2 E2\nG1 X3 E3\n")
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0]["from_mm"], [2,0,0])

    def test_mixed_unretract_move_is_partitioned(self):
        _, paths = extract(HEADER + "M83\nG1 E-1\nG1 X2 E2\n")
        self.assertEqual(paths[0]["from_mm"], [1,0,0])
        self.assertEqual(paths[0]["filament_delta_mm"], 1)

    def test_stationary_prime_counted_separately(self):
        summary, paths = extract(HEADER + "G1 E1\nG1 X1 E2\n")
        self.assertEqual(summary["stationary_extrusion_mm"], 1)
        self.assertEqual(len(paths), 1)

    def test_support_roles(self):
        summary, _ = extract(HEADER + ";TYPE:Support material\nG1 X1 E1\n;TYPE:Support material interface\nG1 X2 E2\n")
        self.assertEqual(summary["segments_by_role"], {"Support material": 1, "Support material interface": 1})

    def test_missing_metadata_remains_unknown(self):
        summary, _ = extract("G21\nG90\nM83\nG1 X0 Y0 Z0\nG1 X1 E1\n")
        self.assertEqual(summary["segments_with_incomplete_metadata"], 1)
        self.assertIsNone(summary["width_range_mm"])

    def test_unsupported_modes_fail_closed(self):
        for command in ("G2 X1 E1", "G91", "G20", "T0", "M200 D1.75", "M221 S0", "M206 X1", "M999", "G28", "G92 X0", "G92", "G92 F10"):
            with self.subTest(command=command), self.assertRaises(InputError):
                extract(HEADER + command + "\nG1 X2 E1\n")

    def test_malformed_coordinates_rejected(self):
        for command in ("G1 X1E1", "G1 X1e-3 E1", "G1 X1 X2 E1", "G1 Xnan E1", "G1 A1 E1"):
            with self.subTest(command=command), self.assertRaises(InputError):
                extract(HEADER + command + "\nG1 X2 E2\n")

    def test_units_and_modes_must_be_explicit(self):
        for text in ("G1 X1 E1", "G21\nG90\nG1 X1 E1", HEADER + "G90\nG1 X1 E1"):
            with self.subTest(text=text), self.assertRaises(InputError):
                extract(text)

    def test_nonfinite_metadata_rejected(self):
        for value in ("nan", "inf", "0", "-1"):
            with self.subTest(value=value), self.assertRaises(InputError):
                extract(HEADER + ";WIDTH:" + value + "\nG1 X1 E1\n")

    def test_no_extrusion_not_success(self):
        with self.assertRaises(InputError):
            extract(HEADER + "G1 X1\n")


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        shutil.copytree(ROOT / "examples/synthetic", self.root, dirs_exist_ok=True)
        self.data = json.loads((self.root / "open.json").read_text())

    def tearDown(self):
        self.directory.cleanup()

    def write(self):
        path = self.root / "open.json"
        path.write_text(json.dumps(self.data))
        return path

    def test_valid_manifest(self):
        _, paths, digest = load_manifest(self.write())
        self.assertEqual(len(paths), 4)
        self.assertEqual(len(digest), 64)

    def test_hash_tamper(self):
        (self.root / "moving.step").write_text("tampered")
        with self.assertRaisesRegex(InputError, "SHA256 mismatch"):
            load_manifest(self.write())

    def test_paths_must_remain_inside_root(self):
        for name in ("../other.step", "/absolute.step", "..\\other.step"):
            with self.subTest(name=name):
                self.data["artifacts"]["moving"]["path"] = name
                with self.assertRaises(InputError): load_manifest(self.write())

    def test_units_version_and_unknown_fields_rejected(self):
        for field, value in (("units", "inch"), ("schema_version", 2), ("schema_version", True), ("mystery", 1)):
            with self.subTest(field=field, value=value):
                original = copy.deepcopy(self.data)
                self.data[field] = value
                with self.assertRaises(InputError): load_manifest(self.write())
                self.data = original

    def test_invalid_rotations_rejected(self):
        for scale in (2, -1):
            self.data["assembly_to_print"][0][0] = scale
            with self.assertRaises(InputError): load_manifest(self.write())

    def test_invalid_sampling_rejected(self):
        for value in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(value=value):
                self.data["path_check"]["max_step_mm"] = value
                with self.assertRaises(InputError): load_manifest(self.write())

    def test_invalid_frames_rejected(self):
        self.data["artifacts"]["moving"]["frame"] = "print"
        with self.assertRaises(InputError): load_manifest(self.write())

    def test_expectation_is_required(self):
        del self.data["path_check"]["expected_outcome"]
        with self.assertRaises(InputError): load_manifest(self.write())


class SamplingTests(unittest.TestCase):
    def test_endpoints_and_max_spacing(self):
        points = sampled_positions([[0,0,0],[1,1,0],[1,1,1]], .3)
        self.assertEqual(points[0], (0,0,0))
        self.assertEqual(points[-1], (1,1,1))
        self.assertTrue(all(math.dist(a,b) <= .3+1e-12 for a,b in zip(points,points[1:])))

    def test_resource_limit(self):
        with self.assertRaises(InputError):
            sampled_positions([[0,0,0],[100,0,0]], .0001)


class ProfileTests(unittest.TestCase):
    def test_block_scripts_secrets_and_network(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile.ini"
            for option in ("post_process = dangerous-script", "printhost_apikey = secret", "print_host = example.invalid", "API_KEY = secret"):
                with self.subTest(option=option):
                    profile.write_text("gcode_comments = 1\nbinary_gcode = 0\n" + option)
                    with self.assertRaises(InputError): inspect_profile(profile)

    def test_real_example_profile(self):
        self.assertEqual(inspect_profile(ROOT / "examples/synthetic/analysis_profile.ini")["nozzle_diameter"], "0.4")


@unittest.skipUnless(importlib.util.find_spec("cadquery"), "geometry extra not installed")
class FrozenGeometryTests(unittest.TestCase):
    def test_known_escape_and_blocked_regressions(self):
        for name, expected in (("open", "sampled_clear"), ("blocked", "collision_found")):
            with self.subTest(name=name):
                data, paths, digest = load_manifest(ROOT / f"examples/synthetic/{name}.json")
                result = check_path(data, paths, digest)
                self.assertEqual(result["outcome"], expected)
                self.assertTrue(result["regression_passed"])
                self.assertEqual(result["unimplemented_gates"]["contact_strength_fem"], "not_implemented")

    def test_cli_mismatch_is_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            shutil.copytree(ROOT / "examples/synthetic", target, dirs_exist_ok=True)
            source = target / "open.json"
            data = json.loads(source.read_text())
            data["path_check"]["expected_outcome"] = "collision_found"
            source.write_text(json.dumps(data))
            with contextlib.redirect_stdout(io.StringIO()):
                status = main(["check-path", str(source), "--output", str(target / "result.json")])
            self.assertEqual(status, 3)


if __name__ == "__main__":
    unittest.main()
