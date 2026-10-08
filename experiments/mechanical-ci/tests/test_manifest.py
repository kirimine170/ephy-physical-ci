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

    def test_section_geometry_provenance_and_validation_scope(self):
        manifest = json.loads((ROOT / "manifest.json").read_text())
        entries = [item for item in manifest["experiments"] if item["id"] == "section-geometry"]
        self.assertEqual(len(entries), 1)
        experiment = entries[0]
        self.assertEqual(experiment["validation_scope"], "finite_static_2d_geometry")
        self.assertEqual(experiment["continuous_collision"], "not_proven")
        self.assertEqual(experiment["physical_validation"], "not_performed")
        self.assertEqual(experiment["repository_cli_integration"], "not_implemented")
        self.assertEqual(experiment["authoring_receipt_scope"], "historical_authoring_environment_only")

        names = {item["path"] for item in manifest["artifacts"]}
        for relative in (
            "README.md", "ENGINEERING_FINDINGS.md", "section_geometry.py",
            "requirements.txt", "tests/test_section_geometry.py",
            "tests/test_fail_closed.py",
            "candidate-manifest.json", "test-results.txt",
        ):
            self.assertIn("section-geometry/" + relative, names)
        provenance = json.loads((ROOT / "section-geometry/candidate-manifest.json").read_text())
        candidate_files = {item["path"]: item["sha256"] for item in provenance["files"]}
        self.assertEqual(len(candidate_files), len(provenance["files"]))
        self.assertEqual(candidate_files["section_geometry.py"], experiment["candidate_source_sha256"])
        integrated_source = ROOT / experiment["entrypoint"]
        self.assertNotEqual(hashlib.sha256(integrated_source.read_bytes()).hexdigest(),
                            candidate_files["section_geometry.py"])
        receipt = ROOT / experiment["authoring_receipt"]
        self.assertEqual(receipt.parent, ROOT / "section-geometry")
        self.assertEqual(hashlib.sha256(receipt.read_bytes()).hexdigest(), candidate_files["test-results.txt"])


if __name__ == "__main__":
    unittest.main()
