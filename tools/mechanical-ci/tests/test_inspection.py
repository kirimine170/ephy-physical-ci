import contextlib
import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from physical_ci.cli import main
from physical_ci.inspection import inspect_length


class LengthInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.subject = {"schema_version": 1, "sample_id": "synthetic-coupon-001",
                        "design_job_ref": "synthetic-design-001", "manufacturing_job_ref": "synthetic-print-001"}
        self.requirement = {"schema_version": 1, "feature_id": "length-A", "requirement_revision": "r1",
                            "unit": "mm", "process_state": "after_support_removal", "measurement_method": "caliper_length",
                            "tolerance": {"lower": 9.9, "upper": 10.1},
                            "judgment_policy": {"name": "interval_containment_v1", "unevaluated_uncertainty": "indeterminate"}}
        self.evidence = self.root / "synthetic-observation.txt"
        self.evidence.write_bytes(b"Synthetic observation only; no actual measurement.\n")
        self.measurement = {**self.subject, **{k: self.requirement[k] for k in
                            ("feature_id", "requirement_revision", "unit", "process_state", "measurement_method")},
                            "value": 10, "source_kind": "synthetic",
                            "uncertainty": {"status": "evaluated", "value": 0.01, "unit": "mm", "basis": "synthetic half-width"},
                            "evidence_refs": [{"path": self.evidence.name, "sha256": hashlib.sha256(self.evidence.read_bytes()).hexdigest()}]}
        self.paths = [self.root / name for name in ("subject.json", "requirement.json", "measurement.json")]
        self.output = self.root / "result.json"

    def save(self):
        for path, data in zip(self.paths, (self.subject, self.requirement, self.measurement)):
            path.write_bytes(json.dumps(data).encode("utf-8"))

    def run_cli(self, omit=(), save=True):
        if save:
            self.save()
        args = ["inspect-length", str(self.paths[0]), "--output", str(self.output)]
        for flag, path in zip(("requirement", "measurement"), self.paths[1:]):
            if flag not in omit:
                args += ["--" + flag, str(path)]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(args)
        return code, json.loads(out.getvalue()), err.getvalue()

    def evaluate(self):
        self.save()
        return inspect_length(*self.paths)[0]

    def assert_input_error(self):
        code, report, explanation = self.run_cli()
        self.assertEqual(code, 2)
        self.assertEqual(report["execution_status"], "error")
        self.assertEqual(report["judgment"], "not_applicable")
        self.assertIn("input error", explanation)
        self.assertFalse(self.output.exists())

    def test_interval_inside_outside_touch_and_overlap(self):
        for value, radius, expected in ((10, .1, "pass"), (9.91, .01, "pass"), (10.09, .01, "pass"),
                                        (9.8, .01, "fail"), (10.2, .01, "fail"), (9.89, .01, "indeterminate"),
                                        (10.11, .01, "indeterminate"), (9.9, .01, "indeterminate"),
                                        (10.1, .01, "indeterminate"), (9.9, 0, "pass"), (10.1, 0, "pass")):
            with self.subTest(value=value, radius=radius):
                self.measurement["value"] = value
                self.measurement["uncertainty"]["value"] = radius
                report = self.evaluate()
                self.assertEqual(report["judgment"], expected)
                self.assertEqual(report["execution_status"], "complete")

    def test_simple_acceptance_and_unknown_uncertainty_policies(self):
        self.requirement["judgment_policy"]["name"] = "simple_acceptance_v1"
        for value, expected in ((9.9, "pass"), (10, "pass"), (10.1, "pass"), (9.89, "fail"), (10.11, "fail")):
            with self.subTest(value=value):
                self.measurement["value"] = value
                self.measurement["uncertainty"]["value"] = 5  # Simple policy uses the point even with known uncertainty.
                self.assertEqual(self.evaluate()["judgment"], expected)
        self.measurement["value"] = 10
        self.measurement["uncertainty"] = {"status": "unevaluated", "reason": "not evaluated"}
        self.assertEqual(self.evaluate()["judgment"], "indeterminate")
        self.requirement["judgment_policy"]["unevaluated_uncertainty"] = "ignore"
        self.assertEqual(self.evaluate()["judgment"], "pass")
        self.assertNotIn("value", self.evaluate()["measurement"]["uncertainty"])
        self.measurement["value"] = 11
        self.assertEqual(self.evaluate()["judgment"], "fail")
        self.requirement["judgment_policy"]["name"] = "interval_containment_v1"
        self.assert_input_error()
        self.requirement["judgment_policy"]["unevaluated_uncertainty"] = "indeterminate"
        self.assertEqual(self.evaluate()["reason"], "uncertainty_unevaluated")

    def test_subject_and_requirement_mismatches_are_not_physical_failure(self):
        for field in ("sample_id", "design_job_ref", "manufacturing_job_ref", "feature_id", "requirement_revision",
                      "process_state", "measurement_method"):
            with self.subTest(field=field):
                original = self.measurement[field]
                self.measurement[field] = "another-binding"
                self.assert_input_error()
                self.measurement[field] = original

    def test_unit_mismatches_and_unsupported_units_never_convert(self):
        for owner, field in ((self.measurement, "unit"), (self.requirement, "unit"), (self.measurement["uncertainty"], "unit")):
            for unit in ("cm", "inch", "MM", None):
                with self.subTest(field=field, unit=unit):
                    original = owner[field]
                    owner[field] = unit
                    self.assert_input_error()
                    owner[field] = original

    def test_missing_requirement_measurement_and_evidence_cannot_pass(self):
        for omit, reason in ((["requirement"], "missing_requirement"), (["measurement"], "missing_measurement"),
                             (["requirement", "measurement"], "missing_requirement")):
            code, report, _ = self.run_cli(omit)
            self.assertEqual(code, 0)
            self.assertEqual(report["judgment"], "indeterminate")
            self.assertEqual(report["execution_status"], "not_run")
            self.assertEqual(report["reason"], reason)
            self.output.unlink()
        self.measurement["evidence_refs"] = []
        self.assertEqual(self.evaluate()["reason"], "missing_evidence")
        self.measurement["evidence_refs"] = [{"path": "absent.txt", "sha256": "0" * 64}]
        self.assertEqual(self.evaluate()["judgment"], "indeterminate")
        self.evidence.write_bytes(b"")
        self.measurement["evidence_refs"][0]["path"] = self.evidence.name
        self.assertEqual(self.evaluate()["reason"], "missing_evidence")

    def test_missing_required_information_and_unknown_fields_rejected(self):
        for owner in (self.subject, self.requirement, self.requirement["tolerance"],
                      self.requirement["judgment_policy"], self.measurement, self.measurement["uncertainty"]):
            for field in list(owner):
                with self.subTest(field=field):
                    value = owner.pop(field)
                    self.assert_input_error()
                    owner[field] = value
            owner["unknown"] = "unsupported"
            self.assert_input_error()
            del owner["unknown"]
        for field in ("sample_id", "feature_id", "measurement_method"):
            old = self.measurement[field]
            self.measurement[field] = " "
            self.assert_input_error()
            self.measurement[field] = old

    def test_invalid_numbers_and_policies_rejected(self):
        for owner, field in ((self.measurement, "value"), (self.measurement["uncertainty"], "value"),
                             (self.requirement["tolerance"], "lower"), (self.requirement["tolerance"], "upper")):
            for invalid in (True, None, "10", -1, float("nan"), float("inf"), 10 ** 110):
                with self.subTest(field=field, invalid=str(invalid)):
                    old = owner[field]
                    owner[field] = invalid
                    self.assert_input_error()
                    owner[field] = old
        self.requirement["tolerance"] = {"lower": 11, "upper": 10}
        self.assert_input_error()
        self.requirement["tolerance"] = {"lower": 10, "upper": 10}
        self.measurement["uncertainty"]["value"] = 0
        self.assertEqual(self.evaluate()["judgment"], "pass")
        self.requirement["judgment_policy"]["name"] = "unknown-standard"
        self.assert_input_error()

    def test_corrupt_duplicate_nonfinite_and_resource_bounded_json(self):
        self.save()
        for raw in (b'{', b'[]', b'\xff', b'{"schema_version":1,"schema_version":1}',
                    b'{"value":1e309}', b'{"value":1e-999}', b'{"value":NaN}', b'{"value":' + b'1' * 129 + b'}',
                    b'[' * 1500 + b']' * 1500, b' ' * (64 * 1024 + 1)):
            with self.subTest(raw=raw[:30]):
                self.paths[2].write_bytes(raw)
                code, report, _ = self.run_cli(save=False)
                self.assertEqual(code, 2)
                self.assertEqual(report["judgment"], "not_applicable")
                self.assertFalse(self.output.exists())

    def test_evidence_integrity_path_and_size_guards(self):
        for path in ("../outside.txt", "C:/private.txt", "/absolute.txt", "sub\\file.txt"):
            self.measurement["evidence_refs"][0]["path"] = path
            self.assert_input_error()
        self.measurement["evidence_refs"][0]["path"] = self.evidence.name
        self.measurement["evidence_refs"][0]["sha256"] = "0" * 64
        self.assert_input_error()
        with patch("physical_ci.inspection.MAX_EVIDENCE_BYTES", 1):
            self.assert_input_error()

    def test_reports_hash_parsed_bytes_preserve_thresholds_and_label_provenance(self):
        before = copy.deepcopy(self.requirement)
        code, report, explanation = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(report, json.loads(self.output.read_text(encoding="utf-8")))
        self.assertEqual(report["evidence_class"], "record")
        self.assertTrue(report["synthetic"])
        self.assertIn("Synthetic fixture", explanation)
        self.assertIn("closed bounds", explanation)
        self.assertNotIn(str(self.root), json.dumps(report))
        self.assertEqual(self.requirement, before)
        for key, path in zip(("subject_sha256", "requirement_sha256", "measurement_sha256"), self.paths):
            self.assertEqual(report["input_hashes"][key], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(report["measurement"]["value"], "10")
        self.output.unlink()
        self.measurement["source_kind"] = "human_measurement"  # Synthetic test of the provenance branch, not a real observation.
        self.assertEqual(self.run_cli()[1]["evidence_class"], "measurement")

    def test_failure_exit_meanings_and_exclusive_output(self):
        self.measurement["value"] = 11
        self.assertEqual(self.run_cli()[0:2][1]["judgment"], "fail")
        previous = self.output.read_bytes()
        self.assertEqual(self.run_cli()[0], 2)
        self.assertEqual(self.output.read_bytes(), previous)
        self.output.unlink()
        self.save()
        self.paths[1].unlink()
        code, report, _ = self.run_cli(save=False)
        self.assertEqual(code, 1)
        self.assertEqual(report["execution_status"], "error")
        self.assertEqual(report["judgment"], "not_applicable")
        self.assertFalse(self.output.exists())

    def test_output_cannot_replace_any_input_or_evidence(self):
        for path in (*self.paths, self.evidence):
            self.output = path
            self.save()
            before = path.read_bytes()
            self.assertEqual(self.run_cli(save=False)[0], 2)
            self.assertEqual(path.read_bytes(), before)

    def test_checked_in_synthetic_examples(self):
        root = ROOT / "examples" / "synthetic" / "length-inspection"
        for name, expected in (("pass", "pass"), ("fail", "fail"), ("indeterminate", "indeterminate")):
            report, _ = inspect_length(root / "subject.json", root / "requirement.json", root / (name + ".json"))
            self.assertEqual(report["judgment"], expected)
            self.assertTrue(report["synthetic"])
            self.assertEqual(report["evidence_class"], "record")


if __name__ == "__main__":
    unittest.main()
