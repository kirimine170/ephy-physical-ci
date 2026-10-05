"""Frozen independent handwritten oracles for the nominal plane audit."""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
import zipfile
from unittest.mock import patch
from types import SimpleNamespace

EXPERIMENT = Path(__file__).resolve().parents[1] / "support-plane"
loader = importlib.util.spec_from_file_location("support_plane_audit", EXPERIMENT / "audit.py")
audit = importlib.util.module_from_spec(loader)
loader.loader.exec_module(audit)
study_loader = importlib.util.spec_from_file_location("support_plane_study", EXPERIMENT / "reproduce.py")
study = importlib.util.module_from_spec(study_loader)
with patch.dict(sys.modules, {"audit": audit}):
    study_loader.loader.exec_module(study)


def specification(raw):
    return {"schema_version": 1, "frame": "gcode_machine_coordinates", "units": "mm",
            "gcode_sha256": hashlib.sha256(raw).hexdigest(), "xy_min": [0, 0], "xy_max": [10, 10],
            "nominal_plane_z_mm": 12, "boundary": "closed"}


def raw_path(role="Support material interface", z="11.8", extra=""):
    return ("G21\nG90\nM83\n;WIDTH:0.4\n;HEIGHT:0.2\n;TYPE:" + role +
            "\nG0 X-2 Y5 Z" + z + "\nG1 X12 Y5 E1\n" + extra).encode()


class PlaneTests(unittest.TestCase):
    def run_audit(self, raw, spec=None):
        return audit.audit_bytes(raw, json.dumps(spec or specification(raw)).encode())

    def test_seven_frozen_independent_oracles(self):
        root = EXPERIMENT / "oracles"
        plan = json.loads((root / "preregistered-oracles.json").read_text())
        for name, case in plan["cases"].items():
            with self.subTest(name=name):
                raw = (root / case["gcode_file"]).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), case["sha256"])
                data = {"schema_version": 1, "gcode_sha256": case["sha256"], **plan["window"]}
                result = self.run_audit(raw, data)
                for key in ("coverage_complete", "known_selected_top_z_mm", "nominal_plane_minus_top_mm"):
                    expected = case["expected"][key]
                    if expected is None or isinstance(expected, bool):
                        self.assertEqual(result[key], expected)
                    else:
                        self.assertAlmostEqual(result[key], expected)

    def test_line_crossing_selected_with_endpoints_outside(self):
        self.assertEqual(audit.xy_intersection([-2, 5, 0], [12, 5, 0], [0, 0], [10, 10]), [1/7, 6/7])

    def test_bounding_box_overlap_is_not_a_line_hit(self):
        self.assertIsNone(audit.xy_intersection([-1, 9.5, 0], [1, 11.5, 0], [0, 0], [10, 10]))

    def test_closed_boundary_and_small_positive_gap(self):
        self.assertIsNotNone(audit.xy_intersection([-1, 9, 0], [1, 11, 0], [0, 0], [10, 10]))
        self.assertIsNone(audit.xy_intersection([-1, 10.00001, 0], [11, 10.00001, 0], [0, 0], [10, 10]))

    def test_width_is_not_a_centerline_expansion(self):
        raw = raw_path(extra="G0 X-2 Y10.1 Z11.9\n;WIDTH:10\nG1 X12 Y10.1 E1\n")
        result = self.run_audit(raw)
        self.assertEqual(result["known_selected_top_z_mm"], 11.8)
        self.assertEqual(result["selected_support_events"], 1)

    def test_height_cannot_change_nominal_command_plane_difference(self):
        for value in ("0.2", "0.4", "1.2"):
            raw = raw_path().replace(b";HEIGHT:0.2", (";HEIGHT:" + value).encode())
            self.assertAlmostEqual(self.run_audit(raw)["nominal_plane_minus_top_mm"], .2)

    def test_negative_signed_difference_is_retained(self):
        result = self.run_audit(raw_path(z="12.2"))
        self.assertLess(result["nominal_plane_minus_top_mm"], 0)
        self.assertEqual(result["physical_contact"], "not_evaluated")

    def test_missing_width_preserves_known_top_but_withholds_difference(self):
        result = self.run_audit(raw_path().replace(b";WIDTH:0.4\n", b""))
        self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["known_selected_top_z_mm"], 11.8)
        self.assertIsNone(result["nominal_plane_minus_top_mm"])

    def test_skirt_brim_wipe_tower_are_not_model_planes(self):
        for role in ("Skirt/Brim", "Skirt", "Brim", "Wipe tower"):
            raw = raw_path(extra=";TYPE:" + role + "\nG0 X-2 Y5 Z12\nG1 X12 Y5 E1\n" +
                           ";TYPE:Bridge infill\n;HEIGHT:0.4\nG0 X-2 Y5 Z12.2\nG1 X12 Y5 E1\n")
            result = self.run_audit(raw)
            self.assertEqual(result["known_first_model_plane_at_or_above_nominal_z_mm"], 12.2)
            self.assertEqual({e["role"] for e in result["known_first_model_plane_witnesses"]}, {"Bridge infill"})

    def test_unknown_role_model_observation_does_not_imply_complete(self):
        raw = raw_path(extra=";TYPE:Mystery\nG0 X-2 Y5 Z12\nG1 X12 Y5 E1\n" +
                       ";TYPE:Bridge infill\nG0 X-2 Y5 Z12.2\nG1 X12 Y5 E1\n")
        result = self.run_audit(raw)
        self.assertEqual(result["known_first_model_plane_at_or_above_nominal_z_mm"], 12.2)
        self.assertFalse(result["coverage_complete"])
        self.assertIsNone(result["nominal_plane_minus_top_mm"])

    def test_hash_mismatch_rejected(self):
        raw = raw_path()
        spec = specification(raw)
        spec["gcode_sha256"] = "0" * 64
        with self.assertRaisesRegex(audit.InputError, "SHA256 mismatch"):
            self.run_audit(raw, spec)

    def test_schema_frame_transform_and_nonfinite_rejected(self):
        raw = raw_path()
        for key, value in (("frame", "assembly"), ("units", "inch"), ("boundary", "open"),
                           ("schema_version", True), ("nominal_plane_z_mm", True),
                           ("nominal_plane_z_mm", float("inf")), ("transform", []),
                           ("xy_min", [0, 0, 0]), ("xy_max", [0, 10])):
            data = specification(raw)
            data[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(audit.InputError):
                self.run_audit(raw, data)

    def test_unsupported_units_offsets_and_arcs_reject_without_scalar(self):
        for command in ("G20", "G92 Z0", "G91", "G2 X1 Y2 I1 J1 E1"):
            with self.subTest(command=command), self.assertRaises(audit.InputError):
                self.run_audit(raw_path(extra=command + "\n"))

    def test_plane_difference_overflow_is_not_a_finite_measurement(self):
        raw = raw_path(z="-" + "1" + "0" * 308)
        data = specification(raw)
        data["nominal_plane_z_mm"] = 1e308
        with self.assertRaisesRegex(audit.InputError, "difference arithmetic overflow"):
            self.run_audit(raw, data)

    def test_hashes_bind_parsed_buffers_when_live_paths_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            gcode, plane = Path(tmp) / "synthetic.gcode", Path(tmp) / "plane.json"
            raw = raw_path()
            plane_raw = json.dumps(specification(raw)).encode()
            gcode.write_bytes(raw); plane.write_bytes(plane_raw)
            original_extract = audit.extract

            def change_live(text, **kwargs):
                gcode.write_bytes(b"changed after read")
                plane.write_bytes(b"changed after read")
                return original_extract(text, **kwargs)

            with patch.object(audit, "extract", side_effect=change_live):
                result = audit.audit(gcode, plane)
            self.assertEqual(result["gcode_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(result["plane_specification_sha256"], hashlib.sha256(plane_raw).hexdigest())
            self.assertEqual(result["known_selected_top_z_mm"], 11.8)

    def test_reproducer_rejects_other_binary_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = Path(tmp) / "other-binary"
            other.write_bytes(b"not the pinned executable")
            result = subprocess.run([sys.executable, str(EXPERIMENT / "reproduce.py"),
                                     "--slicer", str(other), "--output", str(Path(tmp) / "out")],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pinned to the recorded Debian", result.stderr)

    def test_public_oracle_loading_does_not_modify_historical_artifacts(self):
        historical = audit.ROOT / "experiments/mechanical-ci/support-screen-e2e"
        before = {p.relative_to(historical) for p in historical.rglob("*") if p.is_file()}
        result = subprocess.run([sys.executable, "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); import reproduce; "
            "assert callable(reproduce.public_decimal_auditor())", str(EXPERIMENT)],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        after = {p.relative_to(historical) for p in historical.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


class RecordedStudyTests(unittest.TestCase):
    def test_independent_failure_controls_bind_current_reproducer(self):
        root = EXPERIMENT / "oracles"
        record = json.loads((root / "independent-failure-result.json").read_text())
        self.assertEqual(record["reproduce_sha256"], hashlib.sha256((EXPERIMENT / "reproduce.py").read_bytes()).hexdigest())
        self.assertEqual(record["fault_child_sha256"], hashlib.sha256((root / "verify_failure_child.py").read_bytes()).hexdigest())
        self.assertTrue(record["all_failure_controls_passed"])
        self.assertEqual(len(record["observations"]), 2)
        for observation in record["observations"]:
            self.assertNotEqual(observation["exit_code"], 0)
            self.assertFalse(observation["success_summary_exists"])
            self.assertEqual(observation["failure"]["outcome"], "reproduction_failed")

    def test_independent_reviews_bind_current_audit_and_raw_archive(self):
        oracles = EXPERIMENT / "oracles"
        implementation = json.loads((oracles / "independent-result.json").read_text())
        self.assertEqual(implementation["reviewed_audit_sha256"], hashlib.sha256((EXPERIMENT / "audit.py").read_bytes()).hexdigest())
        self.assertEqual(implementation["verifier_sha256"], hashlib.sha256((oracles / "verify_implementation.py").read_bytes()).hexdigest())
        self.assertEqual(implementation["integer_segment_oracles_passed"], 2000)
        self.assertTrue(implementation["all_7_fixtures_passed"])
        raw_review = json.loads((oracles / "independent-run-005.json").read_text())
        self.assertTrue(raw_review["all_4_raw_audits_passed"])
        self.assertEqual(raw_review["verifier_sha256"], hashlib.sha256((oracles / "verify_raw_slices.py").read_bytes()).hexdigest())
        with zipfile.ZipFile(EXPERIMENT / "evidence.zip") as archive:
            self.assertEqual(raw_review["manifest_sha256"], hashlib.sha256(archive.read("manifest.json")).hexdigest())
            self.assertEqual(raw_review["preregistered_sha256"], hashlib.sha256(archive.read("preregistered.json")).hexdigest())

    def test_archive_manifest_and_compact_summary_identity(self):
        with zipfile.ZipFile(EXPERIMENT / "evidence.zip") as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(set(archive.namelist()), set(manifest) | {"manifest.json"})
            for name, digest in manifest.items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest, name)
            self.assertEqual(archive.read("summary.json"), (EXPERIMENT / "summary.json").read_bytes())
            summary = json.loads(archive.read("summary.json"))
            self.assertTrue(summary["recorded_reproduction_passed"])
            self.assertTrue(all(all(row["recorded_reproduction_checks"].values()) for row in summary["observations"]))
            provenance = json.loads(archive.read("provenance.json"))
            for name, digest in provenance["source_sha256"].items():
                self.assertEqual(hashlib.sha256((audit.ROOT / name).read_bytes()).hexdigest(), digest, name)

    def test_all_four_raw_inputs_replay_full_audit(self):
        with zipfile.ZipFile(EXPERIMENT / "evidence.zip") as archive:
            expected = [("0", 12., 0., "Solid infill", .2),
                        ("0.1", 11.7, .3, "Bridge infill", .4),
                        ("0.2", 11.6, .4, "Bridge infill", .4),
                        ("0.3", 11.5, .5, "Bridge infill", .4)]
            for gap, top, difference, role, height in expected:
                prefix = f"contact-{gap}/"
                result = audit.audit_bytes(archive.read(prefix + "toolpath.analysis-only.gcode"),
                                           archive.read(prefix + "plane.json"))
                self.assertEqual(result, json.loads(archive.read(prefix + "plane-report.json")))
                self.assertTrue(result["coverage_complete"])
                self.assertAlmostEqual(result["known_selected_top_z_mm"], top)
                self.assertAlmostEqual(result["nominal_plane_minus_top_mm"], difference)
                witnesses = result["known_first_model_plane_witnesses"]
                self.assertEqual({v["role"] for v in witnesses}, {role})
                self.assertEqual({v["height_metadata_mm"] for v in witnesses}, {height})
                self.assertEqual(result["physical_air_gap"], "not_measured")

    def test_profiles_differ_only_in_requested_setting(self):
        from physical_ci.slicer import inspect_profile
        with zipfile.ZipFile(EXPERIMENT / "evidence.zip") as archive, tempfile.TemporaryDirectory() as tmp:
            settings = []
            for gap in ("0", "0.1", "0.2", "0.3"):
                path = Path(tmp) / f"contact-{gap}.ini"
                path.write_bytes(archive.read(f"inputs/{path.name}"))
                values = inspect_profile(path)
                self.assertEqual(values.pop("support_material_contact_distance"), gap)
                settings.append(values)
            self.assertTrue(all(row == settings[0] for row in settings))


class ReproductionGateTests(unittest.TestCase):
    def observations(self, gap):
        row = study.RECORDED_CASES[gap]
        return ({"coverage_complete": True, "known_selected_top_z_mm": row["support_plane_z_mm"],
                 "nominal_plane_minus_top_mm": 12-row["support_plane_z_mm"]},
                {"known_first_z_mm": row["model_z_mm"], "roles": list(row["roles"]),
                 "height_metadata_mm": list(row["heights_mm"])})

    def test_all_four_recorded_cases_are_required(self):
        for gap in study.RECORDED_CASES:
            report, model = self.observations(gap)
            self.assertTrue(all(study.verify_recorded_case(gap, report, model).values()))
            mutations = [("known_selected_top_z_mm", report["known_selected_top_z_mm"]+.01),
                         ("nominal_plane_minus_top_mm", report["nominal_plane_minus_top_mm"]+.01),
                         ("coverage_complete", False), ("known_selected_top_z_mm", None),
                         ("known_selected_top_z_mm", float("nan"))]
            for field, value in mutations:
                bad = dict(report, **{field: value})
                with self.subTest(gap=gap, field=field), self.assertRaises(study.ReproductionMismatch):
                    study.verify_recorded_case(gap, bad, model)

    def test_bridge_regime_and_zero_gap_model_conditions_are_required(self):
        for gap in study.RECORDED_CASES:
            report, model = self.observations(gap)
            for field, value in (("known_first_z_mm", 12.3), ("known_first_z_mm", None),
                                 ("roles", []), ("roles", ["Perimeter"]),
                                 ("height_metadata_mm", [.3])):
                with self.subTest(gap=gap, field=field), self.assertRaises(study.ReproductionMismatch):
                    study.verify_recorded_case(gap, report, dict(model, **{field: value}))

    def test_consistent_but_different_slicer_output_has_no_success_summary(self):
        # Both the product audit and independent raw auditor see the SAME
        # altered G-code. Their agreement alone must not be called reproduction.
        with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(EXPERIMENT / "evidence.zip") as archive:
            root = Path(tmp)
            binary = root / "mock-pinned-binary"
            binary.write_bytes(b"IO fixture; never executed")
            output = root / "run"
            real_sha = study.sha

            def controlled_sha(path):
                return study.SLICER_SHA256 if Path(path) == binary else real_sha(path)

            def fake_slice(manifest, paths, digest, executable, directory):
                directory = Path(directory)
                directory.mkdir()
                name = directory.name
                raw = archive.read(name + "/toolpath.analysis-only.gcode")
                if name == "contact-0":
                    # The selected support plane becomes 12.1; model Z12.2
                    # remains unchanged. Units, roles, pose and metadata stay valid.
                    import re
                    raw = re.sub(rb"(?m)^(G[01] .*?)Z12(?:\.0*)?(?=\s|$)", rb"\g<1>Z12.1", raw)
                gcode = directory / "toolpath.analysis-only.gcode"
                gcode.write_bytes(raw)
                summary = json.loads(archive.read(name + "/slice-summary.json"))
                summary["gcode_sha256"] = hashlib.sha256(raw).hexdigest()
                return summary, []

            with patch.object(study, "sha", side_effect=controlled_sha), \
                    patch.object(study.subprocess, "run", return_value=SimpleNamespace(stdout="PrusaSlicer-2.9.2+MOCK\n", stderr="")), \
                    patch.object(study, "run_slicer", side_effect=fake_slice):
                with self.assertRaises(study.ReproductionMismatch):
                    study.reproduce(binary, output)
            self.assertFalse((output / "summary.json").exists())
            failure = json.loads((output / "failure.json").read_text())
            self.assertEqual(failure["outcome"], "reproduction_failed")
            self.assertEqual(failure["case"], "contact-0")
            self.assertAlmostEqual(failure["observed_support_plane_z_mm"], 12.1)
            self.assertEqual(failure["expected"]["support_plane_z_mm"], 12.)


if __name__ == "__main__":
    unittest.main()
