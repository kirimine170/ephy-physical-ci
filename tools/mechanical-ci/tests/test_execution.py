import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from physical_ci.cli import main
from physical_ci.errors import BackendError, InputError
from physical_ci.gcode import extract
from physical_ci.manifest import load_manifest
from physical_ci.slicer import run_slicer

GCODE = "G21\nG90\nM82\nG92 E0\nG1 X0 Y0 Z0.2\n;TYPE:Perimeter\n;WIDTH:0.4\n;HEIGHT:0.2\n;Z:0.2\nG1 X1 E1\n"


class OutputTests(unittest.TestCase):
    def run_quiet(self, args):
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            return main(args)

    def test_analyze_and_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "test.gcode"
            source.write_text(GCODE)
            status = self.run_quiet(["analyze-gcode", str(source), "--output", str(root/"summary.json"), "--segments", str(root/"paths.jsonl")])
            self.assertEqual(status, 0)
            self.assertEqual(json.loads((root/"summary.json").read_text())["extrusion_segments"], 1)
            self.assertEqual(len((root/"paths.jsonl").read_text().splitlines()), 1)

    def test_same_output_as_source_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "test.gcode"
            source.write_text(GCODE)
            self.assertEqual(self.run_quiet(["analyze-gcode", str(source), "--output", str(source)]), 2)
            self.assertEqual(source.read_text(), GCODE)

    def test_hardlink_output_does_not_truncate_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory)/"test.gcode", Path(directory)/"output.json"
            source.write_text(GCODE)
            os.link(source, output)
            self.assertEqual(self.run_quiet(["analyze-gcode", str(source), "--output", str(output)]), 2)
            self.assertEqual(source.read_text(), GCODE)

    def test_output_collision_is_preflighted_before_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, summary, paths = root/"test.gcode", root/"summary.json", root/"paths.jsonl"
            source.write_text(GCODE)
            paths.write_text("keep")
            self.assertEqual(self.run_quiet(["analyze-gcode", str(source), "--output", str(summary), "--segments", str(paths)]), 2)
            self.assertFalse(summary.exists())
            self.assertEqual(paths.read_text(), "keep")

    def test_unknown_initial_coordinates_and_extrusion_fail(self):
        for text in ("G21\nG90\nM83\nG1 X1 E1\n", "G21\nG90\nM82\nG1 X0 Y0 Z0\nG1 X1 E1\n"):
            with self.subTest(text=text), self.assertRaises(InputError):
                extract(text)


class SlicerAdapterTests(unittest.TestCase):
    def setUp(self):
        self.data, self.paths, self.digest = load_manifest(ROOT / "examples/synthetic/open.json")

    def fake_backend(self, args, **kwargs):
        if args[1] == "--help":
            return subprocess.CompletedProcess(args, 0, "PrusaSlicer-2.9.2+test\n", "")
        Path(args[args.index("--output") + 1]).write_text(GCODE)
        self.assertNotIn("shell", kwargs)
        self.assertIn("--config-compatibility", args)
        self.assertIn("disable", args)
        return subprocess.CompletedProcess(args, 0, "sliced", "")

    def test_success_is_versioned_hashed_and_not_printer_ready(self):
        with tempfile.TemporaryDirectory() as directory, patch("physical_ci.slicer.shutil.which", return_value=__file__), patch("physical_ci.slicer.subprocess.run", side_effect=self.fake_backend):
            summary, paths = run_slicer(self.data,self.paths,self.digest,"fake-slicer",directory)
            self.assertEqual(summary["slicer"]["version"], "2.9.2")
            self.assertFalse(summary["printer_ready"])
            self.assertFalse(summary["assembly_to_print_geometry_verified"])
            self.assertEqual(len(summary["gcode_sha256"]), 64)
            self.assertEqual(len(paths), 1)

    def test_zero_exit_without_output_is_failure(self):
        with tempfile.TemporaryDirectory() as directory, patch("physical_ci.slicer.shutil.which", return_value=__file__), patch("physical_ci.slicer.subprocess.run", return_value=subprocess.CompletedProcess([],0,"PrusaSlicer-2.9.2\n", "")):
            with self.assertRaises(BackendError):
                run_slicer(self.data,self.paths,self.digest,"fake",directory)

    def test_stale_output_rejected(self):
        with tempfile.TemporaryDirectory() as directory, patch("physical_ci.slicer.shutil.which", return_value=__file__), patch("physical_ci.slicer.subprocess.run", side_effect=self.fake_backend):
            path = Path(directory)/"toolpath.analysis-only.gcode"
            path.write_text(GCODE)
            with self.assertRaises(InputError):
                run_slicer(self.data,self.paths,self.digest,"fake",directory)
            self.assertEqual(path.read_text(), GCODE)

    def test_reserved_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory, patch("physical_ci.slicer.shutil.which", return_value=__file__), patch("physical_ci.slicer.subprocess.run", side_effect=self.fake_backend):
            link = Path(directory)/"slicer.local.log"
            link.symlink_to(self.paths["profile"])
            original = self.paths["profile"].read_bytes()
            with self.assertRaises(InputError):
                run_slicer(self.data,self.paths,self.digest,"fake",directory)
            self.assertEqual(self.paths["profile"].read_bytes(), original)

    def test_wrong_version_and_prerelease_rejected(self):
        for header in ("PrusaSlicer-2.8.0", "PrusaSlicer-2.9.2-alpha1", "unknown"):
            with self.subTest(header=header), tempfile.TemporaryDirectory() as directory, patch("physical_ci.slicer.shutil.which", return_value=__file__), patch("physical_ci.slicer.subprocess.run", return_value=subprocess.CompletedProcess([],0,header,"")):
                with self.assertRaises(BackendError):
                    run_slicer(self.data,self.paths,self.digest,"fake",directory)

    def test_missing_backend_rejected(self):
        with tempfile.TemporaryDirectory() as directory, patch("physical_ci.slicer.shutil.which", return_value=None):
            with self.assertRaises(BackendError):
                run_slicer(self.data,self.paths,self.digest,"missing",directory)

    def test_timeout_is_failure(self):
        with tempfile.TemporaryDirectory() as directory, patch("physical_ci.slicer.shutil.which", return_value=__file__), patch("physical_ci.slicer.subprocess.run", side_effect=subprocess.TimeoutExpired("fake",15)):
            with self.assertRaises(BackendError):
                run_slicer(self.data,self.paths,self.digest,"fake",directory)


@unittest.skipUnless(os.environ.get("PRUSA_SLICER_TEST_BINARY"), "set PRUSA_SLICER_TEST_BINARY for real pinned CLI integration")
class RealSlicerIntegrationTests(unittest.TestCase):
    def test_original_synthetic_fixture(self):
        data, paths, digest = load_manifest(ROOT / "examples/synthetic/open.json")
        with tempfile.TemporaryDirectory() as directory:
            summary, segments = run_slicer(data,paths,digest,os.environ["PRUSA_SLICER_TEST_BINARY"],directory)
            self.assertGreater(len(segments), 0)
            self.assertGreater(summary["segments_by_role"].get("Support material",0),0)
            self.assertEqual(summary["segments_with_incomplete_metadata"], 0)


if __name__ == "__main__":
    unittest.main()
