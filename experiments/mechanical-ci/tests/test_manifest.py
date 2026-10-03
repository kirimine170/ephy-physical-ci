"""Verify the public experiment evidence index without executing solvers."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EvidenceManifestTests(unittest.TestCase):
    def test_declared_artifacts_match_recorded_bytes(self):
        manifest = json.loads((ROOT / "manifest.json").read_text())
        self.assertEqual(manifest["schema_version"], "mechanical-experiment-index/1")
        self.assertEqual(manifest["license_status"], "not_selected")
        names = set()
        for artifact in manifest["artifacts"]:
            name = artifact["path"]
            relative = PurePosixPath(name)
            self.assertFalse(relative.is_absolute())
            self.assertNotIn("..", relative.parts)
            self.assertNotIn(name, names)
            names.add(name)
            path = (ROOT / name).resolve()
            self.assertTrue(path.is_relative_to(ROOT))
            self.assertTrue(path.is_file())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), artifact["sha256"], name)
        self.assertIn("escape-search/results/open.json", names)
        self.assertIn("escape-search/results/closed.json", names)
        self.assertIn("frame-compliance/compact_summary.json", names)

    def test_stored_scope_does_not_claim_physical_retention(self):
        manifest = json.loads((ROOT / "manifest.json").read_text())
        for experiment in manifest["experiments"]:
            self.assertEqual(experiment["physical_retention"], "unknown")
            self.assertEqual(experiment["input_scope"], "original_synthetic_fixture")
        for kind in ("open", "closed"):
            result = json.loads((ROOT / "escape-search/results" / (kind + ".json")).read_text())
            self.assertFalse(result["retention_proven"])
            self.assertEqual(result["script_sha256"], hashlib.sha256((ROOT / "escape-search/experiment.py").read_bytes()).hexdigest())
        result = json.loads((ROOT / "frame-compliance/compact_summary.json").read_text())
        self.assertFalse(result["material"]["calibrated"])
        self.assertEqual(result["validation_scope"]["physical_retention_or_failure_load"], "unknown")
        self.assertEqual(result["generator_sha256"], hashlib.sha256((ROOT / "frame-compliance/run_experiment.py").read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
