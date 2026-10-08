"""Direct regression oracles for malformed source bytes and section contours."""
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from section_geometry import load_mesh_bytes, mesh_audit, section_material, section_relation


def ring(points):
    return np.array([[x, y, 0] for x, y in points], dtype=float)


SQUARE = ring([(0, 0), (2, 0), (2, 2), (0, 2), (0, 0)])


class FailClosedTests(unittest.TestCase):
    def test_positive_overlap_below_or_at_tolerance_remains_explicit(self):
        first = trimesh.creation.box(extents=[2, 2, 2])
        second = first.copy()
        second.apply_translation([1.75, 0, 0])
        for tolerance in (1.0, 0.5):
            with self.subTest(tolerance=tolerance):
                result = section_relation(first, second, 0, tolerance)
                self.assertAlmostEqual(result['overlap_area'], 0.5)
                self.assertEqual(result['separation'], 0)
                self.assertEqual(result['area_tolerance'], tolerance)
                self.assertEqual(result['status'], 'at_or_below_area_tolerance_at_sample')

    def material(self, rings, closed=True):
        mesh = trimesh.creation.box()
        section = SimpleNamespace(is_closed=closed, discrete=rings)
        with patch.object(mesh, "section", return_value=section):
            return section_material(mesh, 0)

    def test_open_entities_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "open entities"):
            self.material([SQUARE], closed=False)

    def test_open_and_degenerate_rings_are_rejected(self):
        for points in (SQUARE[:-1], ring([(0, 0), (1, 0), (0, 0)])):
            with self.subTest(points=points.tolist()):
                with self.assertRaisesRegex(ValueError, "Open or degenerate"):
                    self.material([points])

    def test_self_intersecting_ring_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Invalid section polygon"):
            self.material([ring([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])])

    def test_crossing_touching_and_duplicate_rings_are_rejected(self):
        # A valid single-body mesh reaches the contour checks; body_count
        # cannot short-circuit these independent negative controls.
        for dx in (1, 2, 0):
            with self.subTest(dx=dx):
                second = SQUARE + [dx, 0, 0]
                with self.assertRaisesRegex(ValueError, "Crossing, duplicate or touching"):
                    self.material([SQUARE, second])

    def test_nonfinite_ring_is_rejected(self):
        invalid = SQUARE.copy()
        invalid[2, 0] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite 3D points"):
            self.material([invalid])

    def test_strictly_nested_ring_preserves_hole_in_either_order(self):
        from shapely.geometry import Point
        inner = ring([(.5, .5), (1.5, .5), (1.5, 1.5), (.5, 1.5), (.5, .5)])
        for rings in ([SQUARE, inner], [inner, SQUARE]):
            result = self.material(rings)
            self.assertAlmostEqual(result.area, 3)
            self.assertFalse(result.contains(Point(1, 1)))

    def test_finite_height_required_by_public_material_helper(self):
        for z in (float("nan"), float("inf"), -float("inf")):
            with self.assertRaisesRegex(ValueError, "Finite section height"):
                section_material(trimesh.creation.box(), z)

    def test_nonfinite_mesh_is_rejected_before_audit_or_section(self):
        mesh = trimesh.creation.box()
        mesh.vertices[0, 0] = float("nan")
        for operation in (lambda: mesh_audit(mesh), lambda: section_material(mesh, 0)):
            with self.assertRaisesRegex(ValueError, "vertices must be finite"):
                operation()

    def test_exact_welding_preserves_faces_and_coordinates(self):
        source = trimesh.creation.box()
        raw = source.export(file_type="stl")
        for file_type in ("stl", "STL"):
            mesh = load_mesh_bytes(raw, file_type)
            self.assertEqual(len(mesh.faces), len(source.faces))
            self.assertTrue(mesh.is_watertight)
            np.testing.assert_array_equal(
                np.unique(mesh.vertices, axis=0), np.unique(source.vertices, axis=0))

    def test_scene_and_other_formats_rejected_before_loading(self):
        for file_type in ("glb", "gltf", "3mf", "obj", "ply", None):
            with self.subTest(file_type=file_type):
                with patch("section_geometry.trimesh.load") as loader:
                    with self.assertRaisesRegex(ValueError, "Only STL input"):
                        load_mesh_bytes(b"format must not be parsed", file_type)
                    loader.assert_not_called()

    def test_cli_rejects_transformed_scene_without_writing_report(self):
        scene = trimesh.Scene(trimesh.creation.box())
        transform = np.eye(4)
        transform[:3, 3] = [4, 5, 6]
        scene.apply_transform(transform)
        raw = scene.export(file_type="glb")
        script = Path(__file__).resolve().parents[1] / "section_geometry.py"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "transformed.glb"
            output = Path(directory) / "report.json"
            source.write_bytes(raw)
            result = subprocess.run(
                [sys.executable, str(script), str(source), "--output", str(output)],
                capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Only STL input", result.stderr)
            self.assertFalse(output.exists())
            self.assertEqual(source.read_bytes(), raw)

    def test_cli_rejects_nonfinite_stl_instead_of_cleaning_it(self):
        valid = trimesh.creation.box().export(file_type="stl")
        # One additional malformed original triangle would be silently dropped
        # by Trimesh process=True, leaving the box apparently watertight.
        bad_face = struct.pack("<12fH", *([0.0] * 3 + [float("nan")] + [0.0] * 8), 0)
        malformed = valid[:80] + struct.pack("<I", 13) + valid[84:] + bad_face
        script = Path(__file__).resolve().parents[1] / "section_geometry.py"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invalid.stl"
            output = Path(directory) / "report.json"
            source.write_bytes(malformed)
            result = subprocess.run(
                [sys.executable, str(script), str(source), "--output", str(output)],
                capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("vertices must be finite", result.stderr)
            self.assertFalse(output.exists())
            self.assertEqual(source.read_bytes(), malformed)

    def test_cli_reports_processing_and_hashes_consumed_bytes(self):
        import hashlib
        raw = trimesh.creation.box().export(file_type="stl")
        script = Path(__file__).resolve().parents[1] / "section_geometry.py"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "box.stl"
            output = Path(directory) / "report.json"
            source.write_bytes(raw)
            result = subprocess.run(
                [sys.executable, str(script), str(source), "--output", str(output)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["inputs"][0]["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertTrue(report["inputs"][0]["audit"]["edge_watertight"])
            self.assertIn("automatic cleanup disabled", report["mesh_processing"])


if __name__ == "__main__":
    unittest.main()
