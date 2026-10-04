"""Validate compact synthetic E2E evidence; do not run PrusaSlicer in CI."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import unittest

ROOT = Path(__file__).resolve().parents[1] / "support-screen-e2e"


class SupportE2EEvidenceTests(unittest.TestCase):
    def test_manifest_bytes_and_paths(self):
        manifest = json.loads((ROOT / "bundle-manifest.json").read_text())
        self.assertFalse(manifest["product_code_modified"])
        seen = set()
        for item in manifest["files"]:
            name = item["path"]
            relative = PurePosixPath(name)
            self.assertFalse(relative.is_absolute())
            self.assertNotIn("..", relative.parts)
            self.assertNotIn(name, seen)
            seen.add(name)
            path = (ROOT / name).resolve()
            self.assertTrue(path.is_relative_to(ROOT))
            data = path.read_bytes()
            self.assertEqual(len(data), item["size_bytes"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), item["sha256"], name)
        self.assertEqual(seen, {str(p.relative_to(ROOT)) for p in ROOT.rglob("*")
                               if p.is_file() and p.name != "bundle-manifest.json"})

    def test_recorded_scope_and_preregistered_cases(self):
        result = json.loads((ROOT / "run-003/summary.json").read_text())
        plan = json.loads((ROOT / "run-003/preregistered-plan.json").read_text())
        self.assertTrue(result["checks_passed"])
        self.assertEqual(result["physical_validation"], "not_performed")
        self.assertEqual(result["support_removal"], "not_implemented")
        self.assertFalse(result["printer_ready"])
        self.assertEqual([c["name"] for c in plan["cases"]], ["a_auto", "a_none", "b_auto"])
        for case in result["cases"]:
            self.assertTrue(case["coverage_complete"])
            self.assertEqual(case["input_hashes_before"], case["input_hashes_after"])
            self.assertTrue(case["repeat_byte_equal"])
            self.assertTrue(case["bad_hash_rejected"])
            if case["case"] == "a_none":
                self.assertEqual(case["screened_support_events"], 0)
                self.assertEqual(case["observed_hit_count"], 0)
            else:
                self.assertGreater(case["observed_hit_count"], 0)
                self.assertEqual(set(case["interior_witnesses"]), {"body", "interface"})
        provenance = json.loads((ROOT / "run-003/provenance.json").read_text())
        self.assertEqual(provenance["script_sha256"], hashlib.sha256((ROOT / "run_e2e.py").read_bytes()).hexdigest())

    def test_hash_window_remains_a_documented_control(self):
        result = json.loads((ROOT / "hash-window-control-final/summary.json").read_text())
        self.assertEqual({c["mutated"] for c in result["controls"]}, {"gcode", "roi"})
        for case in result["controls"]:
            self.assertTrue(case["reproduced"])
            self.assertEqual(case["exit_code"], 0)
            self.assertEqual(case["before"], case["report_hashes"])
            self.assertNotEqual(case["before"], case["after"])


if __name__ == "__main__":
    unittest.main()
