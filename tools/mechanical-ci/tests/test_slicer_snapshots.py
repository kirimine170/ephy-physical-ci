"""Synthetic input-drift and output-publication controls; no real unsafe commands."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from physical_ci import slicer
from physical_ci import manifest as manifest_module
from physical_ci.cli import main
from physical_ci.errors import BackendError, InputError
from physical_ci.manifest import load_manifest, sha256

GCODE = "G21\nG90\nM82\nG92 E0\nG1 X0 Y0 Z0.2\n;TYPE:Perimeter\n;WIDTH:0.4\n;HEIGHT:0.2\nG1 X1 E1\n"


class InputSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.inputs = self.root / "inputs"
        shutil.copytree(ROOT / "examples/synthetic", self.inputs)
        self.manifest_path = self.inputs / "open.json"
        self.data, self.paths, self.manifest_digest = load_manifest(self.manifest_path)
        self.output = self.root / "result"
        self.original = {k: self.paths[k].read_bytes() for k in ("profile", "print_mesh")}
        self.copied_paths = {}
        self.backend_read = {}
        self.generated = None
        self.calls = []

    def tearDown(self):
        self.temp.cleanup()

    def backend(self, args, **kwargs):
        self.calls.append(args)
        if args[1] == "--help":
            return subprocess.CompletedProcess(args, 0, "PrusaSlicer-2.9.2+test\n", "")
        self.copied_paths = {"profile": Path(args[args.index("--load")+1]), "print_mesh": Path(args[-1])}
        self.backend_read = {k: p.read_bytes() for k, p in self.copied_paths.items()}
        self.generated = Path(args[args.index("--output")+1])
        self.generated.write_text(GCODE)
        return subprocess.CompletedProcess(args, 0, "synthetic slice complete", "")

    def run_adapter(self, backend=None):
        with patch.object(slicer.shutil, "which", return_value=__file__), \
             patch.object(slicer.subprocess, "run", side_effect=backend or self.backend):
            return slicer.run_slicer(self.data, self.paths, self.manifest_digest, "fake", self.output)

    def assert_no_success_artifacts(self, destination_may_exist=False):
        if not destination_may_exist:
            self.assertFalse((self.output / "toolpath.analysis-only.gcode").exists())
        self.assertFalse((self.output / "summary.json").exists())
        self.assertFalse((self.output / "segments.jsonl").exists())
        self.assertEqual(list(self.output.glob(".slicer-run-*")), [])

    def test_copied_profile_inspected_and_copied_inputs_consumed(self):
        inspected = []
        original_inspect = slicer.inspect_profile
        def inspect(path):
            inspected.append(path)
            self.assertNotEqual(path, self.paths["profile"])
            self.assertEqual(path.read_bytes(), self.original["profile"])
            return original_inspect(path)
        with patch.object(slicer, "inspect_profile", side_effect=inspect):
            summary, segments = self.run_adapter()
        self.assertEqual(len(inspected), 1)
        self.assertEqual(self.backend_read, self.original)
        self.assertEqual(summary["input_binding"], "verified_private_snapshots")
        self.assertEqual(summary["consumed_input_sha256"], {k: hashlib.sha256(v).hexdigest() for k, v in self.backend_read.items()})
        for key, path in self.copied_paths.items():
            self.assertNotEqual(path, self.paths[key])
            self.assertEqual(path.name, self.paths[key].name)
            self.assertFalse(path.exists())
        self.assertEqual(len(segments), 1)
        self.assertEqual((self.output / "toolpath.analysis-only.gcode").read_text(), GCODE)
        self.assertEqual(summary["gcode_sha256"], hashlib.sha256(GCODE.encode()).hexdigest())

    def test_original_ini_and_mesh_edits_during_help_do_not_change_consumed_bytes(self):
        def drift(args, **kwargs):
            result = self.backend(args, **kwargs)
            if args[1] == "--help":
                self.paths["profile"].write_bytes(self.original["profile"] + b"\npost_process = UNUSED_SENTINEL\n")
                self.paths["print_mesh"].write_bytes(b"changed original mesh; never consumed")
            return result
        summary, _ = self.run_adapter(drift)
        self.assertEqual(self.backend_read, self.original)
        self.assertNotEqual(sha256(self.paths["profile"]), summary["consumed_input_sha256"]["profile"])

    def test_original_files_can_disappear_after_snapshot(self):
        def delete(args, **kwargs):
            result = self.backend(args, **kwargs)
            if args[1] == "--help":
                self.paths["profile"].unlink()
                self.paths["print_mesh"].unlink()
            return result
        self.run_adapter(delete)
        self.assertEqual(self.backend_read, self.original)

    def test_drift_before_snapshot_is_rejected_before_backend(self):
        for key in ("profile", "print_mesh"):
            with self.subTest(key=key):
                self.paths[key].write_bytes(self.original[key] + b"changed")
                with self.assertRaisesRegex(InputError, "SHA256 mismatch"):
                    self.run_adapter()
                self.assertEqual(self.calls, [])
                self.assert_no_success_artifacts()
                self.paths[key].write_bytes(self.original[key])

    def test_hash_matched_unsafe_profile_rejected_before_backend(self):
        raw = self.original["profile"] + b"\npost_process = UNUSED_SENTINEL\n"
        self.paths["profile"].write_bytes(raw)
        self.data["artifacts"]["profile"]["sha256"] = hashlib.sha256(raw).hexdigest()
        with self.assertRaisesRegex(InputError, "disallowed"):
            self.run_adapter()
        self.assertEqual(self.calls, [])
        self.assert_no_success_artifacts()

    def test_snapshot_drift_during_help_refuses_export(self):
        def drift(args, **kwargs):
            result = self.backend(args, **kwargs)
            if args[1] == "--help":
                copied = next(self.output.glob(".slicer-run-*/inputs/profile/*"))
                copied.write_bytes(copied.read_bytes() + b"\npost_process = UNUSED_SENTINEL\n")
            return result
        with self.assertRaisesRegex(InputError, "snapshot changed"):
            self.run_adapter(drift)
        self.assertEqual(len(self.calls), 1)
        self.assert_no_success_artifacts()

    def test_snapshot_mesh_drift_during_export_is_not_success(self):
        def drift(args, **kwargs):
            result = self.backend(args, **kwargs)
            if args[1] != "--help":
                self.copied_paths["print_mesh"].write_bytes(b"persistent mesh mutation")
            return result
        with self.assertRaisesRegex(InputError, "snapshot changed"):
            self.run_adapter(drift)
        self.assertTrue((self.output / "slicer.local.log").exists())
        self.assert_no_success_artifacts()

    def test_snapshot_profile_replacement_by_symlink_is_rejected(self):
        def replace(args, **kwargs):
            result = self.backend(args, **kwargs)
            if args[1] != "--help":
                copied = self.copied_paths["profile"]
                copied.unlink()
                copied.symlink_to(self.paths["profile"])
            return result
        with self.assertRaisesRegex(InputError, "not a regular copied file"):
            self.run_adapter(replace)
        self.assert_no_success_artifacts()

    def test_snapshot_mutation_after_parse_still_prevents_publication(self):
        original_extract = slicer.extract
        def mutate(text):
            result = original_extract(text)
            self.copied_paths["profile"].write_bytes(b"changed after parsing")
            return result
        with patch.object(slicer, "extract", side_effect=mutate), self.assertRaisesRegex(InputError, "snapshot changed"):
            self.run_adapter()
        self.assert_no_success_artifacts()

    def test_generated_live_file_drift_cannot_change_published_buffer(self):
        original_extract = slicer.extract
        def mutate(text):
            result = original_extract(text)
            self.generated.write_bytes(b"changed after the bounded read")
            return result
        with patch.object(slicer, "extract", side_effect=mutate):
            summary, _ = self.run_adapter()
        self.assertEqual((self.output / "toolpath.analysis-only.gcode").read_bytes(), GCODE.encode())
        self.assertEqual(summary["gcode_sha256"], hashlib.sha256(GCODE.encode()).hexdigest())

    def test_final_output_collision_is_never_overwritten(self):
        def collision(args, **kwargs):
            result = self.backend(args, **kwargs)
            if args[1] != "--help":
                (self.output / "toolpath.analysis-only.gcode").write_bytes(b"other run")
            return result
        with self.assertRaises(FileExistsError):
            self.run_adapter(collision)
        self.assertEqual((self.output / "toolpath.analysis-only.gcode").read_bytes(), b"other run")
        self.assert_no_success_artifacts(destination_may_exist=True)

    def test_concurrent_local_log_is_never_overwritten(self):
        def collision(args, **kwargs):
            result = self.backend(args, **kwargs)
            if args[1] != "--help":
                (self.output / "slicer.local.log").write_text("other log")
            return result
        with self.assertRaises(FileExistsError):
            self.run_adapter(collision)
        self.assertEqual((self.output / "slicer.local.log").read_text(), "other log")
        self.assert_no_success_artifacts()

    def test_failed_backend_keeps_log_without_final_gcode(self):
        def fail(args, **kwargs):
            result = self.backend(args, **kwargs)
            if args[1] != "--help":
                result.returncode = 4
            return result
        with self.assertRaises(BackendError):
            self.run_adapter(fail)
        self.assertTrue((self.output / "slicer.local.log").exists())
        self.assert_no_success_artifacts()

    def test_parser_failure_does_not_publish_generated_gcode(self):
        def malformed(args, **kwargs):
            result = self.backend(args, **kwargs)
            if args[1] != "--help":
                self.generated.write_text("G2 X1 E1\n")
            return result
        with self.assertRaises(InputError):
            self.run_adapter(malformed)
        self.assert_no_success_artifacts()

    def test_bounded_snapshot_reads(self):
        with patch.dict(slicer.INPUT_LIMITS, {"profile": 8}), self.assertRaisesRegex(InputError, "1 to 8 bytes"):
            self.run_adapter()
        self.assertEqual(self.calls, [])
        self.assert_no_success_artifacts()

    def test_generated_size_limit_before_publication(self):
        with patch.object(slicer, "MAX_GCODE_BYTES", 8), self.assertRaisesRegex(InputError, "1 to 8 bytes"):
            self.run_adapter()
        self.assert_no_success_artifacts()

    def test_manifest_object_changes_do_not_relabel_consumed_run(self):
        def mutate(args, **kwargs):
            result = self.backend(args, **kwargs)
            if args[1] == "--help":
                self.data["slicing"]["center_mm"][0] = 999
                self.data["slicing"]["support_mode"] = "none"
            return result
        summary, _ = self.run_adapter(mutate)
        self.assertEqual(summary["slicer_center_mm"], [90, 90])
        self.assertEqual(summary["support_mode"], "auto")
        self.assertIn("--support-material", self.calls[-1])

    def test_manifest_parse_and_hash_use_one_read_buffer(self):
        original_bytes = self.manifest_path.read_bytes()
        original_resolve = manifest_module.resolve_artifact
        changed = dict(self.data, name="edited after JSON was parsed")
        def mutate(root, artifact):
            result = original_resolve(root, artifact)
            self.manifest_path.write_text(json.dumps(changed))
            return result
        with patch.object(manifest_module, "resolve_artifact", side_effect=mutate):
            parsed, _, digest = load_manifest(self.manifest_path)
        self.assertEqual(parsed["name"], self.data["name"])
        self.assertEqual(digest, hashlib.sha256(original_bytes).hexdigest())
        self.assertNotEqual(digest, sha256(self.manifest_path))

    def test_cli_snapshot_failure_has_no_success_summary_or_segments(self):
        def mutate(args, **kwargs):
            result = self.backend(args, **kwargs)
            if args[1] != "--help":
                self.copied_paths["profile"].write_bytes(b"changed")
            return result
        with patch.object(slicer.shutil, "which", return_value=__file__), \
             patch.object(slicer.subprocess, "run", side_effect=mutate), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = main(["slice", str(self.manifest_path), "--slicer", "fake", "--output-dir", str(self.output), "--segments"])
        self.assertEqual(result, 2)
        self.assert_no_success_artifacts()


if __name__ == "__main__":
    unittest.main()
