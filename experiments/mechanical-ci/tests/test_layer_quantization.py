"""New regression coverage for the preserved synthetic layer evidence.

Reconstructed from published bytes, not recovered from an unpublished test.
Only the bounded historical audit runs; no slicer or printer is invoked.
"""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "layer-quantization"
EXPECTED_CASES = [f"{orientation}_{height}" for orientation in ("flat", "side")
                  for height in ("2.4", "2.5", "2.6", "2.7", "2.8")]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class LayerQuantizationTests(unittest.TestCase):
    def test_bundle_and_archive_members_match_hashes_and_lengths(self):
        bundle = json.loads((EXPERIMENT / "bundle-manifest.json").read_text())
        self.assertEqual(set(bundle), {p.name for p in EXPERIMENT.iterdir()
                                      if p.is_file()} - {"bundle-manifest.json"})
        for name, record in bundle.items():
            raw = (EXPERIMENT / name).read_bytes()
            self.assertEqual(len(raw), record["bytes"], name)
            self.assertEqual(sha(raw), record["sha256"], name)
        raw = (EXPERIMENT / "evidence.zip").read_bytes()
        self.assertEqual(len(raw), 652260)
        self.assertEqual(sha(raw), "69d2e05e88e7548474c44952f5bebc470a7f2b9e90fa6ace27b8eaa2d286b6a7")
        manifest = json.loads((EXPERIMENT / "data-manifest.json").read_text())
        with zipfile.ZipFile(EXPERIMENT / "evidence.zip") as archive:
            self.assertEqual(len(archive.namelist()), len(set(archive.namelist())))
            self.assertEqual(set(archive.namelist()), set(manifest))
            for member in archive.infolist():
                name = member.filename
                path = PurePosixPath(name)
                self.assertFalse(path.is_absolute())
                self.assertNotIn("..", path.parts)
                self.assertNotIn("\\", name)
                self.assertFalse(stat.S_ISLNK(member.external_attr >> 16))
                raw = archive.read(member)
                self.assertEqual(len(raw), manifest[name]["bytes"], name)
                self.assertEqual(sha(raw), manifest[name]["sha256"], name)

    def test_ten_raw_cases_replay_summary_without_modifying_evidence(self):
        before = {p.name: sha(p.read_bytes()) for p in EXPERIMENT.iterdir() if p.is_file()}
        manifest = json.loads((EXPERIMENT / "data-manifest.json").read_text())
        cases = json.loads((EXPERIMENT / "cases.json").read_text())
        self.assertEqual([row["name"] for row in cases], EXPECTED_CASES)
        expected = json.loads((EXPERIMENT / "summary.json").read_text())
        self.assertEqual(set(expected), set(EXPECTED_CASES))
        with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(EXPERIMENT / "evidence.zip") as archive:
            root = Path(tmp)
            # Validate each member before writing into an isolated disposable copy.
            self.assertEqual(set(archive.namelist()), set(manifest))
            for name in archive.namelist():
                relative = PurePosixPath(name)
                self.assertFalse(relative.is_absolute())
                self.assertNotIn("..", relative.parts)
                self.assertNotIn("\\", name)
                raw = archive.read(name)
                self.assertEqual(len(raw), manifest[name]["bytes"])
                self.assertEqual(sha(raw), manifest[name]["sha256"])
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            shutil.copyfile(EXPERIMENT / "cases.json", root / "cases.json")
            result = subprocess.run([sys.executable, str(EXPERIMENT / "audit.py"),
                                     "--root", str(root)], capture_output=True, text=True,
                                    timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            actual = json.loads((root / "summary.json").read_text())
            self.assertEqual(actual, expected)
        self.assertEqual(before, {p.name: sha(p.read_bytes()) for p in EXPERIMENT.iterdir() if p.is_file()})

    def test_pose_audit_rejects_changed_translation_rotation_and_units(self):
        with zipfile.ZipFile(EXPERIMENT / "evidence.zip") as archive:
            case = "flat_2.4"
            source = archive.read(f"results/{case}/analysis_only.3mf")
            for old, new in [(b"85 84 1.20000005", b"86 84 1.20000005"),
                             (b"1 0 0 0 1 0 0 0 1 85", b"2 0 0 0 1 0 0 0 1 85"),
                             (b'unit="millimeter"', b'unit="inch"')]:
                with self.subTest(mutation=new), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    for name in [f"inputs/{case}.stl", f"results/{case}/resolved.json",
                                 f"results/{case}/plate_1.gcode"]:
                        target = root / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(archive.read(name))
                    (root / "cases.json").write_text(json.dumps([{"name": case}]))
                    target = root / f"results/{case}/analysis_only.3mf"
                    with zipfile.ZipFile(io.BytesIO(source)) as original, zipfile.ZipFile(target, "w") as changed:
                        for name in original.namelist():
                            raw = original.read(name)
                            if name == "3D/3dmodel.model":
                                self.assertIn(old, raw)
                                raw = raw.replace(old, new)
                            changed.writestr(name, raw)
                    result = subprocess.run([sys.executable, str(EXPERIMENT / "audit.py"),
                                             "--root", str(root)], capture_output=True, text=True,
                                            timeout=60)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse((root / "summary.json").exists())

    def test_corrected_signatures_and_bounded_observations(self):
        summary = json.loads((EXPERIMENT / "summary.json").read_text())
        signature = lambda name: summary[name]["model_path_signature_sha256"]
        self.assertEqual(signature("flat_2.4"), signature("flat_2.5"))
        self.assertNotEqual(signature("flat_2.7"), signature("flat_2.8"))
        for height, top, count, ymax in [("2.4", "2.4", 12, "82.19"),
                                       ("2.5", "2.4", 12, "82.29"),
                                       ("2.6", "2.6", 13, "82.39"),
                                       ("2.7", "2.8", 14, "82.49"),
                                       ("2.8", "2.8", 14, "82.59")]:
            flat, side = summary[f"flat_{height}"], summary[f"side_{height}"]
            self.assertEqual((flat["model_top_Z"], flat["model_layer_count"]), (top, count))
            self.assertEqual((side["model_top_Z"], side["model_layer_count"]), ("8", 40))
            self.assertEqual(side["outer_at_Z0p4"]["xy_centerline_bounds"]["Y"], ["80.21", ymax])
        index = json.loads((ROOT / "manifest.json").read_text())
        experiment = next(row for row in index["experiments"] if row["id"] == "layer-quantization")
        self.assertEqual(experiment["physical_retention"], "unknown")
        self.assertEqual(experiment["physical_dimensional_accuracy"], "not_measured")


if __name__ == "__main__":
    unittest.main()
