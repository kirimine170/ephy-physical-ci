"""Synthetic tool schema/IO tests and conditional real CadQuery sweep oracles."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from physical_ci.cli import main
from physical_ci.errors import BackendError, InputError
from physical_ci.manifest import sha256
from physical_ci.tool import classify, load_tool_spec, measure, screen_tool, step_snapshot

HAVE_CADQUERY = importlib.util.find_spec("cadquery") is not None


def specification(step):
    return {"schema_version": 1, "units": "mm", "frame": "assembly",
            "obstacle": {"path": step.name, "sha256": sha256(step), "frame": "assembly"},
            "tool": {"kind": "flat_end_cylinder", "radius_mm": 2, "length_mm": 2,
                     "tip_mm": [0, 0, -1], "axis": [0, 0, 1], "travel_mm": 6},
            "numeric_epsilon_mm": 1e-7, "numeric_epsilon_mm3": 1e-9}


class FakeShape:
    """Only for schema/snapshot/dispatch checks, never a geometry oracle."""
    def __init__(self, volume=500., distance=.5, common_volume=0., valid=True):
        self.volume, self.gap, self.common_volume, self.valid = volume, distance, common_volume, valid

    def Solids(self): return [self]
    def isValid(self): return self.valid
    def Volume(self): return self.volume
    def Faces(self): return [1]
    def Edges(self): return [1]
    def Vertices(self): return [1]
    def BoundingBox(self):
        return SimpleNamespace(xmin=-6., xmax=6., ymin=-6., ymax=6., zmin=0., zmax=3.)
    def intersect(self, other): return FakeShape(self.common_volume)
    def distance(self, other): return self.gap


def fake_cq(importer=None, shape=None):
    obstacle = shape or FakeShape()
    return SimpleNamespace(__version__="synthetic-mock",
                           importers=SimpleNamespace(importStep=importer or
                                                     (lambda path: SimpleNamespace(vals=lambda: [obstacle]))),
                           Solid=SimpleNamespace(makeCylinder=lambda r, length, p, d:
                                                 FakeShape(math.pi * r * r * length)),
                           Vector=lambda *values: tuple(values))


class DecisionTests(unittest.TestCase):
    def test_positive_gap_requires_exact_zero_overlap(self):
        cases = [(0, .5, "model_clear"), (0, 0, "indeterminate"),
                 (0, 1e-7, "indeterminate"), (0, .9e-7, "indeterminate"),
                 (1e-12, 0, "indeterminate"), (1e-9, 0, "indeterminate"),
                 (1e-8, 0, "interference"), (1, .5, "indeterminate"),
                 (float("nan"), 0, "indeterminate"), (0, float("inf"), "indeterminate"),
                 (-1, 0, "indeterminate"), (0, -1, "indeterminate"),
                 (None, .5, "indeterminate"), (0, None, "indeterminate")]
        for volume, distance, expected in cases:
            with self.subTest(volume=volume, distance=distance):
                self.assertEqual(classify(volume, distance, 1e-7, 1e-9)[0], expected)

    def test_kernel_exception_nonfinite_and_invalid_common_cannot_clear(self):
        for bad in (float("nan"), float("inf"), True):
            with self.subTest(bad=bad):
                shape = FakeShape(common_volume=bad)
                volume, _, outcome, _ = measure(shape, FakeShape(), 1e-7, 1e-9)
                self.assertIsNone(volume)
                self.assertEqual(outcome, "indeterminate")
        obstacle = FakeShape()
        with patch.object(obstacle, "intersect", side_effect=RuntimeError("synthetic fault")):
            result = measure(obstacle, FakeShape(), 1e-7, 1e-9)
            self.assertEqual(result[2], "indeterminate")
            self.assertIn("intersection_kernel_failure", result[3])
        with patch.object(obstacle, "distance", side_effect=RuntimeError("synthetic fault")):
            result = measure(obstacle, FakeShape(), 1e-7, 1e-9)
            self.assertEqual(result[2], "indeterminate")
        with patch.object(obstacle, "intersect", return_value=FakeShape(1, valid=False)):
            result = measure(obstacle, FakeShape(), 1e-7, 1e-9)
            self.assertEqual(result[2], "indeterminate")
            self.assertIn("invalid_intersection_shape", result[3])


class SpecAndSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.step = self.root / "synthetic.step"
        # IO fixtures are intentionally not claimed to be valid kernel geometry.
        self.step.write_bytes(b"synthetic STEP bytes for IO mocks only\n")
        self.manifest = self.root / "tool.json"
        self.output = self.root / "report.json"
        self.data = specification(self.step)

    def tearDown(self): self.directory.cleanup()

    def write(self):
        self.manifest.write_text(json.dumps(self.data), encoding="utf-8")
        return self.manifest

    def run_quiet(self, output=None):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main(["screen-tool", str(self.manifest), "--output", str(output or self.output)])

    def test_sweep_formula_normalized_axis_and_zero_travel(self):
        spec, source, digest = load_tool_spec(self.write())
        self.assertEqual(spec["sweep_from_mm"], [0, 0, -3])
        self.assertEqual(spec["sweep_to_mm"], [0, 0, 5])
        self.assertEqual(spec["sweep_length_mm"], 8)
        self.assertEqual(source, self.step)
        self.assertEqual(digest, sha256(self.manifest))
        self.data["tool"]["travel_mm"] = 0
        spec, _, _ = load_tool_spec(self.write())
        self.assertEqual(spec["sweep_to_mm"], [0, 0, -1])
        self.assertEqual(spec["sweep_length_mm"], 2)
        self.data["tool"]["axis"] = [0, 0, 1 + 2e-13]
        spec, _, _ = load_tool_spec(self.write())
        self.assertEqual(spec["axis"], [0, 0, 1])

    def test_version_units_frame_unknown_and_missing_fields(self):
        original = copy.deepcopy(self.data)
        for key, value in (("schema_version", True), ("schema_version", 1.0), ("schema_version", 2),
                           ("units", "inch"), ("frame", "print"), ("frame", "gcode_machine_coordinates"),
                           ("name", "unrecognized")):
            with self.subTest(key=key, value=value):
                self.data = copy.deepcopy(original)
                self.data[key] = value
                with self.assertRaises(InputError): load_tool_spec(self.write())
        for key in original:
            self.data = copy.deepcopy(original)
            del self.data[key]
            with self.subTest(missing=key), self.assertRaises(InputError): load_tool_spec(self.write())

    def test_tool_dimensions_axis_vectors_and_unknown_motion_rejected(self):
        original = copy.deepcopy(self.data)
        cases = [("radius_mm", 0), ("radius_mm", -1), ("radius_mm", True), ("length_mm", 0),
                 ("travel_mm", -1), ("travel_mm", True), ("radius_mm", float("nan")),
                 ("radius_mm", float("inf")), ("tip_mm", [0, 0]), ("tip_mm", [False, 0, 0]),
                 ("tip_mm", [0, 0, "1"]), ("axis", [0, 0, 0]), ("axis", [0, 0, 2]),
                 ("axis", [0, 0, 1.000001]), ("axis", [0, 0, float("inf")]),
                 ("kind", "ball_end"), ("rotation", [0, 1, 0]), ("waypoints_mm", [[0, 0, 0]])]
        for key, value in cases:
            self.data = copy.deepcopy(original)
            self.data["tool"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(InputError): load_tool_spec(self.write())
        for key in ("numeric_epsilon_mm", "numeric_epsilon_mm3"):
            for value in (0, -1, True, float("nan"), 10 ** 400):
                self.data = copy.deepcopy(original)
                self.data[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(InputError): load_tool_spec(self.write())

    def test_derived_geometry_arithmetic_overflow(self):
        original = copy.deepcopy(self.data)
        for values in ({"length_mm": 1e308, "travel_mm": 1e308}, {"radius_mm": 1e308},
                       {"tip_mm": [0, 0, -1e308], "length_mm": 1e308},
                       {"radius_mm": 1e-300}, {"travel_mm": 1e-300},
                       {"tip_mm": [0, 0, 1e308]}):
            self.data = copy.deepcopy(original)
            self.data["tool"].update(values)
            with self.subTest(values=values), self.assertRaises(InputError): load_tool_spec(self.write())

    def test_artifact_root_suffix_hash_format_and_frame(self):
        original = copy.deepcopy(self.data)
        cases = [("path", "../synthetic.step"), ("path", "/absolute.step"),
                 ("path", "C:/absolute.step"), ("path", "..\\synthetic.step"),
                 ("path", ""), ("path", True), ("path", "missing.step"),
                 ("frame", "print"), ("sha256", "A" * 64), ("sha256", True),
                 ("sha256", "short"), ("mystery", 1)]
        for key, value in cases:
            self.data = copy.deepcopy(original)
            self.data["obstacle"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(InputError): load_tool_spec(self.write())
        self.step.rename(self.root / "synthetic.stl")
        self.data = copy.deepcopy(original)
        self.data["obstacle"]["path"] = "synthetic.stl"
        with self.assertRaises(InputError): load_tool_spec(self.write())

    def test_strict_json_duplicate_overflow_underflow_depth_and_size(self):
        text = json.dumps(self.data)
        malformed = ["null", "[]", "{", text.replace('"schema_version": 1', '"schema_version": 1,"schema_version": 1'),
                     text.replace('"radius_mm": 2', '"radius_mm": 2,"radius_mm": 3'),
                     text.replace('"radius_mm": 2', '"radius_mm": 1e400'),
                     text.replace('"travel_mm": 6', '"travel_mm": 1e-400'),
                     text.replace('"travel_mm": 6', '"travel_mm": 1e-999999999999999999999999999999'),
                     "[" * 2000 + "]" * 2000, " " * (64 * 1024 + 1)]
        for bad in malformed:
            self.manifest.write_text(bad)
            with self.subTest(prefix=bad[:80]), self.assertRaises(InputError): load_tool_spec(self.manifest)
        self.manifest.write_bytes(b"\xff")
        with self.assertRaises(InputError): load_tool_spec(self.manifest)

    def test_snapshot_read_bytes_hash_import_identity_and_cleanup(self):
        before = self.step.read_bytes()
        with step_snapshot(self.step, sha256(self.step)) as (snapshot, digest):
            self.assertNotEqual(snapshot, self.step)
            self.assertEqual(snapshot.read_bytes(), before)
            self.assertEqual(digest, hashlib.sha256(before).hexdigest())
        self.assertFalse(snapshot.exists())
        self.assertEqual(self.step.read_bytes(), before)

    def test_hash_mismatch_and_step_limits(self):
        self.write()
        self.step.write_bytes(b"changed")
        self.assertEqual(self.run_quiet(), 2)
        self.assertFalse(self.output.exists())
        for size in (0, 64 * 1024 * 1024 + 1):
            with self.step.open("wb") as stream: stream.truncate(size)
            self.data["obstacle"]["sha256"] = sha256(self.step)
            self.write()
            self.assertEqual(self.run_quiet(), 2)
            self.assertFalse(self.output.exists())

    def test_live_source_change_never_changes_imported_snapshot(self):
        expected = self.step.read_bytes()
        captured = []
        def importer(path):
            frozen = Path(path)
            captured.append(frozen)
            self.step.write_bytes(b"live source changed after the read")
            self.assertEqual(frozen.read_bytes(), expected)
            return SimpleNamespace(vals=lambda: [FakeShape()])
        spec, source, digest = load_tool_spec(self.write())
        with patch.dict(sys.modules, {"cadquery": fake_cq(importer=importer)}):
            result = screen_tool(spec, source, digest)
        self.assertEqual(result["input"]["step_sha256"], hashlib.sha256(expected).hexdigest())
        self.assertTrue(result["input"]["snapshot_hash_verified"])
        self.assertFalse(captured[0].exists())

    def test_private_snapshot_tamper_rejected_before_output(self):
        def importer(path):
            Path(path).write_bytes(b"tampered private snapshot")
            return SimpleNamespace(vals=lambda: [FakeShape()])
        self.write()
        with patch.dict(sys.modules, {"cadquery": fake_cq(importer=importer)}):
            self.assertEqual(self.run_quiet(), 2)
        self.assertFalse(self.output.exists())

    def test_mock_dispatch_determinism_and_required_limits(self):
        self.write()
        with patch.dict(sys.modules, {"cadquery": fake_cq()}):
            self.assertEqual(self.run_quiet(), 0)
            second = self.root / "report2.json"
            self.assertEqual(self.run_quiet(second), 0)
        self.assertEqual(self.output.read_bytes(), second.read_bytes())
        report = json.loads(self.output.read_text())
        self.assertEqual(report["command"], "screen-tool")
        self.assertTrue(report["model_clear"])
        self.assertFalse(report["full_tool_assembly_verified"])
        self.assertFalse(report["grip_access_verified"])
        self.assertFalse(report["physical_safety_verified"])
        self.assertFalse(report["printer_ready"])
        self.assertEqual(report["physical_validation"], "not_performed")
        self.assertEqual(report["support_removal"], "not_implemented")
        self.assertEqual(report["support_breakage"], "not_implemented")

    def test_sweep_kernel_failure_or_contradiction_is_indeterminate(self):
        self.write()
        for sweep, expected in ((FakeShape(float("nan")), "invalid_swept_cylinder"),
                                (FakeShape(1), "kernel_sweep_volume_contradiction"),
                                (FakeShape(valid=False), "invalid_swept_cylinder")):
            backend = fake_cq()
            backend.Solid.makeCylinder = lambda *args: sweep
            spec, source, digest = load_tool_spec(self.manifest)
            with patch.dict(sys.modules, {"cadquery": backend}):
                result = screen_tool(spec, source, digest)
            self.assertEqual(result["outcome"], "indeterminate")
            self.assertFalse(result["model_clear"])
            self.assertFalse(result["sweep"]["geometry_verified"])
            self.assertIn(expected, result["reasons"])
            json.dumps(result, allow_nan=False)
        backend = fake_cq()
        def fail(*args): raise RuntimeError("synthetic cylinder fault")
        backend.Solid.makeCylinder = fail
        with patch.dict(sys.modules, {"cadquery": backend}):
            result = screen_tool(spec, source, digest)
        self.assertEqual(result["reasons"], ["sweep_kernel_failure"])

    def test_mock_interference_and_indeterminate_are_reports_not_physical_passes(self):
        self.write()
        for volume, gap, outcome in ((1, 0, "interference"), (0, 0, "indeterminate")):
            output = self.root / (outcome + ".json")
            with patch.dict(sys.modules, {"cadquery": fake_cq(shape=FakeShape(distance=gap, common_volume=volume))}):
                self.assertEqual(self.run_quiet(output), 0)
            result = json.loads(output.read_text())
            self.assertEqual(result["outcome"], outcome)
            self.assertFalse(result["model_clear"])
            self.assertFalse(result["physical_safety_verified"])

    def test_output_inputs_existing_and_hardlinks_are_preserved(self):
        self.write()
        before = self.step.read_bytes(), self.manifest.read_bytes()
        with patch("physical_ci.cli.screen_tool") as backend:
            for output in (self.step, self.manifest): self.assertEqual(self.run_quiet(output), 2)
            self.output.write_text("keep")
            self.assertEqual(self.run_quiet(), 2)
            link = self.root / "linked.json"
            os.link(self.step, link)
            self.assertEqual(self.run_quiet(link), 2)
            backend.assert_not_called()
        self.assertEqual(self.output.read_text(), "keep")
        self.assertEqual(before, (self.step.read_bytes(), self.manifest.read_bytes()))

    def test_mock_malformed_multisolid_invalid_and_nonfinite_geometry_rejected(self):
        spec, source, digest = load_tool_spec(self.write())
        def malformed(path): raise RuntimeError("synthetic malformed STEP")
        with patch.dict(sys.modules, {"cadquery": fake_cq(importer=malformed)}), self.assertRaises(InputError):
            screen_tool(spec, source, digest)
        for shape in (FakeShape(valid=False), FakeShape(volume=float("nan")), FakeShape(volume=0)):
            with patch.dict(sys.modules, {"cadquery": fake_cq(shape=shape)}), self.assertRaises(InputError):
                screen_tool(spec, source, digest)
        shape = FakeShape()
        with patch.object(shape, "Solids", return_value=[FakeShape(), FakeShape()]):
            with patch.dict(sys.modules, {"cadquery": fake_cq(shape=shape)}), self.assertRaises(InputError):
                screen_tool(spec, source, digest)

    def test_missing_existing_geometry_extra_is_explicit(self):
        spec, source, digest = load_tool_spec(self.write())
        with patch.dict(sys.modules, {"cadquery": None}), self.assertRaises(BackendError):
            screen_tool(spec, source, digest)


@unittest.skipUnless(HAVE_CADQUERY, "existing CadQuery/OCCT geometry extra unavailable; real sweep oracle not run")
class KernelOracleTests(unittest.TestCase):
    def setUp(self):
        import cadquery as cq
        self.cq = cq
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.step = self.root / "original-synthetic.step"
        self.manifest = self.root / "tool.json"

    def tearDown(self): self.directory.cleanup()

    def bore(self, hole_radius):
        block = self.cq.Solid.makeBox(12, 12, 3, self.cq.Vector(-6, -6, 0))
        bore = self.cq.Solid.makeCylinder(hole_radius, 5, self.cq.Vector(0, 0, -1))
        return block.cut(bore)

    def run_shape(self, shape, tool_changes=None):
        # Export and later independently import frozen bytes through the stage.
        self.cq.exporters.export(shape, str(self.step))
        data = specification(self.step)
        data["tool"].update(tool_changes or {})
        self.manifest.write_text(json.dumps(data))
        spec, source, digest = load_tool_spec(self.manifest)
        return screen_tool(spec, source, digest)

    def test_r2_hole2point5_has_independent_half_mm_gap(self):
        result = self.run_shape(self.bore(2.5))
        self.assertEqual(result["outcome"], "model_clear")
        self.assertEqual(result["intersection_mm3"], 0)
        self.assertAlmostEqual(result["minimum_distance_mm"], .5, places=7)

    def test_r2_hole1point5_interferes_even_with_clear_centerline(self):
        result = self.run_shape(self.bore(1.5))
        self.assertEqual(result["outcome"], "interference")
        self.assertAlmostEqual(result["intersection_mm3"], math.pi * (2 ** 2 - 1.5 ** 2) * 3, places=6)
        self.assertAlmostEqual(result["minimum_distance_mm"], 0, places=7)

    def test_equal_radius_hole_contact_is_indeterminate(self):
        result = self.run_shape(self.bore(2))
        self.assertEqual(result["outcome"], "indeterminate")
        self.assertFalse(result["model_clear"])
        self.assertAlmostEqual(result["minimum_distance_mm"], 0, places=7)

    def test_clear_endpoints_still_hit_middle_thin_wall(self):
        wall = self.cq.Solid.makeBox(12, 12, .1, self.cq.Vector(-6, -6, 0))
        first = self.cq.Solid.makeCylinder(2, 2, self.cq.Vector(0, 0, -3))
        last = self.cq.Solid.makeCylinder(2, 2, self.cq.Vector(0, 0, 3))
        self.assertEqual(wall.intersect(first).Volume(), 0)
        self.assertEqual(wall.intersect(last).Volume(), 0)
        result = self.run_shape(wall)
        self.assertEqual(result["outcome"], "interference")
        self.assertAlmostEqual(result["intersection_mm3"], math.pi * 2 ** 2 * .1, places=6)

    def test_whole_sweep_containment_is_interference(self):
        block = self.cq.Solid.makeBox(20, 20, 20, self.cq.Vector(-10, -10, -10))
        result = self.run_shape(block)
        self.assertEqual(result["outcome"], "interference")
        self.assertAlmostEqual(result["intersection_mm3"], math.pi * 2 ** 2 * 8, places=6)
        self.assertAlmostEqual(result["minimum_distance_mm"], 0, places=7)

    def test_zero_travel_still_checks_entire_initial_cylinder(self):
        result = self.run_shape(self.bore(2.5), {"travel_mm": 0, "tip_mm": [0, 0, 1]})
        self.assertEqual(result["sweep"]["length_mm"], 2)
        self.assertEqual(result["outcome"], "model_clear")
        self.assertAlmostEqual(result["minimum_distance_mm"], .5, places=7)

    def test_rigid_transform_preserves_volume_and_gap(self):
        angle = math.radians(37)
        c, s = math.cos(angle), math.sin(angle)
        for hole_radius in (2.5, 1.5, 2):
            with self.subTest(hole_radius=hole_radius):
                block = self.bore(hole_radius)
                before = self.run_shape(block)
                transformed = block.rotate((0, 0, 0), (0, 1, 0), 37).translate((8, -3, 5))
                after = self.run_shape(transformed, {"tip_mm": [8 - s, -3, 5 - c], "axis": [s, 0, c]})
                self.assertEqual(before["outcome"], after["outcome"])
                self.assertAlmostEqual(before["intersection_mm3"], after["intersection_mm3"], places=6)
                self.assertAlmostEqual(before["minimum_distance_mm"], after["minimum_distance_mm"], places=7)

    def test_real_malformed_and_multisolid_step_rejected(self):
        self.step.write_bytes(b"not a STEP file\n")
        self.manifest.write_text(json.dumps(specification(self.step)))
        spec, source, digest = load_tool_spec(self.manifest)
        with self.assertRaises(InputError): screen_tool(spec, source, digest)
        compound = self.cq.Compound.makeCompound([
            self.cq.Solid.makeBox(1, 1, 1), self.cq.Solid.makeBox(1, 1, 1, self.cq.Vector(3, 0, 0))])
        with self.assertRaises(InputError): self.run_shape(compound)

    def test_real_cli_round_trip_uses_frozen_hash(self):
        self.run_shape(self.bore(2.5))
        report = self.root / "report.json"
        with contextlib.redirect_stdout(io.StringIO()):
            status = main(["screen-tool", str(self.manifest), "--output", str(report)])
        self.assertEqual(status, 0)
        result = json.loads(report.read_text())
        self.assertEqual(result["outcome"], "model_clear")
        self.assertEqual(result["input"]["step_sha256"], sha256(self.step))


if __name__ == "__main__": unittest.main()
