"""Synthetic regression records: no printer, real specimen, or generated measurement."""
import contextlib
import copy
import hashlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from physical_ci.cli import main
from physical_ci.errors import InputError
from physical_ci.fabrication import record_fabrication
from physical_ci.inspection import BindingMismatch, SUBJECT_FIELDS, inspect_length, read_regular_bytes


class FabricationRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.subject = {"schema_version": 1, "sample_id": "synthetic-coupon-001",
                        "design_job_ref": "synthetic-design-001", "manufacturing_job_ref": "synthetic-print-001"}
        self.part = {"schema_version": 1, "part_id": "synthetic-rack-module", "design_revision": "r1",
                     "artifact_sha256": hashlib.sha256(b"declared digest only; no artifact exists").hexdigest()}
        self.observation = {**self.subject, **self.part, "process_state": "after_support_removal",
                            "source_kind": "synthetic",
                            "print_conditions": {
                                "printer_ref": {"status": "known", "value": "synthetic-printer"},
                                "material_ref": {"status": "known", "value": "synthetic-material"},
                                "profile_ref": {"status": "known", "value": "synthetic-profile"},
                                "nozzle_diameter_mm": {"status": "known", "value": 0.4},
                                "layer_height_mm": {"status": "known", "value": 0.2},
                                "orientation": {"status": "known", "value": {
                                    "frame": "synthetic-build-plate", "description": "datum A toward plate"}}},
                            "support_removal": {"status": "partial", "description": "Synthetic description only"},
                            "fit_observation": {"status": "not_tested",
                                                "target_ref": {"status": "unknown", "reason": "No synthetic mate selected"},
                                                "description": "No actual assembly or physical inspection"}}
        self.paths = [self.root / name for name in ("subject.json", "part.json", "observation.json")]
        self.output = self.root / "fabrication-record.json"

    def save(self):
        for path, data in zip(self.paths, (self.subject, self.part, self.observation)):
            path.write_bytes((json.dumps(data, indent=2) + "\n").encode("utf-8"))

    def run_cli(self, save=True):
        if save:
            self.save()
        args = ["record-fabrication", str(self.paths[0]), "--part", str(self.paths[1]),
                "--observation", str(self.paths[2]), "--output", str(self.output)]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(args)
        return code, json.loads(out.getvalue()), err.getvalue()

    def evaluate(self):
        self.save()
        return record_fabrication(*self.paths)

    def assert_input_error(self, save=True, reason="invalid_input"):
        code, report, explanation = self.run_cli(save=save)
        self.assertEqual(code, 2)
        self.assertEqual(report["command"], "record-fabrication")
        self.assertEqual(report["execution_status"], "error")
        self.assertEqual(report["judgment"], "not_applicable")
        self.assertEqual(report["reason"], reason)
        self.assertEqual(report["artifact_hash_verification"], "not_performed")
        self.assertEqual(report["physical_validation"], "not_performed")
        self.assertFalse(report["printer_ready"])
        self.assertIn("input error", explanation)
        self.assertFalse(self.output.exists())

    def strict_objects(self):
        conditions = self.observation["print_conditions"]
        return [self.subject, self.part, self.observation, conditions, *conditions.values(),
                conditions["orientation"]["value"], self.observation["support_removal"],
                self.observation["fit_observation"], self.observation["fit_observation"]["target_ref"]]

    def test_complete_record_preserves_bindings_and_declares_no_physical_judgment(self):
        before = copy.deepcopy((self.subject, self.part, self.observation))
        code, report, explanation = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(report, json.loads(self.output.read_text(encoding="utf-8")))
        self.assertEqual(report["execution_status"], "complete")
        self.assertEqual(report["judgment"], "not_applicable")
        self.assertEqual(report["evidence_class"], "record")
        self.assertTrue(report["synthetic"])
        self.assertEqual(report["subject"], self.subject)
        self.assertEqual(report["part"], self.part)
        expected = copy.deepcopy(self.observation)
        expected["print_conditions"]["nozzle_diameter_mm"]["value"] = "0.4"
        expected["print_conditions"]["layer_height_mm"]["value"] = "0.2"
        self.assertEqual(report["observation"], expected)
        self.assertEqual((self.subject, self.part, self.observation), before)
        self.assertEqual(report["artifact_hash_verification"], "not_performed")
        self.assertEqual(report["physical_validation"], "not_performed")
        self.assertFalse(report["printer_ready"])
        self.assertIn("Synthetic fixture", explanation)
        self.assertNotIn(str(self.root), json.dumps(report))
        for field in ("measurement", "requirement", "uncertainty", "verified_evidence_sha256"):
            self.assertNotIn(field, report)

    def test_human_provenance_is_an_observation_without_a_physical_pass(self):
        # Synthetic input exercising the declared-human branch; no real observation occurred.
        self.observation["source_kind"] = "human_observation"
        self.observation["support_removal"]["status"] = "removed"
        self.observation["fit_observation"] = {
            "status": "assembled", "target_ref": {"status": "known", "value": "synthetic-mate-r1"},
            "description": "Synthetic declaration of assembly"}
        code, report, explanation = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(report["evidence_class"], "observation")
        self.assertFalse(report["synthetic"])
        self.assertEqual(report["judgment"], "not_applicable")
        self.assertFalse(report["printer_ready"])
        self.assertIn("Declared operator observation", explanation)

    def test_input_hashes_bind_exact_bytes_and_protected_paths(self):
        self.save()
        # Whitespace and key layout are evidence bytes, not canonicalized JSON.
        for index, path in enumerate(self.paths):
            path.write_bytes(path.read_bytes() + b" " * (index + 1))
        report, protected = record_fabrication(*self.paths)
        self.assertEqual(protected, self.paths)
        for key, path in zip(("subject_sha256", "part_sha256", "observation_sha256"), self.paths):
            self.assertEqual(report["input_hashes"][key], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertNotEqual(report["input_hashes"][key], hashlib.sha256(path.read_bytes().rstrip()).hexdigest())

    def test_artifact_digest_is_only_declared_and_never_reads_an_artifact(self):
        self.part["artifact_sha256"] = self.observation["artifact_sha256"] = "a" * 64
        self.save()
        with patch("physical_ci.inspection.read_regular_bytes", wraps=read_regular_bytes) as read:
            report, _ = record_fabrication(*self.paths)
        self.assertEqual([Path(call.args[0]) for call in read.call_args_list], self.paths)
        self.assertEqual(report["part"]["artifact_sha256"], "a" * 64)
        self.assertEqual(report["artifact_hash_verification"], "not_performed")
        for extra in ("artifact_path", "artifact_verified", "physical_pass"):
            self.part[extra] = "unsupported"
            self.assert_input_error()
            del self.part[extra]

    def test_subject_part_revision_and_artifact_binding_mismatches_are_input_errors(self):
        for field in (*SUBJECT_FIELDS, "part_id", "design_revision", "artifact_sha256"):
            with self.subTest(field=field):
                old = self.observation[field]
                self.observation[field] = "b" * 64 if field == "artifact_sha256" else "another-binding"
                self.save()
                with self.assertRaises(BindingMismatch):
                    record_fabrication(*self.paths)
                self.assert_input_error(reason="binding_mismatch")
                self.observation[field] = old

    def test_missing_and_unknown_fields_are_rejected_at_every_object(self):
        for index, owner in enumerate(self.strict_objects()):
            for field in list(owner):
                with self.subTest(object=index, missing=field):
                    original = owner.pop(field)
                    self.assert_input_error()
                    owner[field] = original
            with self.subTest(object=index, unknown=True):
                owner["unsupported"] = "must not be silently discarded"
                self.assert_input_error()
                del owner["unsupported"]

    def test_all_three_schema_versions_require_integer_one(self):
        for owner in (self.subject, self.part, self.observation):
            for invalid in (True, False, 1.0, "1", 2, None):
                with self.subTest(version=invalid):
                    owner["schema_version"] = invalid
                    self.assert_input_error()
            owner["schema_version"] = 1

    def test_blank_nontext_and_whitespace_identifiers_are_rejected(self):
        targets = [(self.subject, field) for field in SUBJECT_FIELDS]
        targets += [(self.part, field) for field in ("part_id", "design_revision")]
        targets += [(self.observation, field) for field in (*SUBJECT_FIELDS, "part_id", "design_revision", "process_state")]
        conditions = self.observation["print_conditions"]
        targets += [(conditions[field], "value") for field in ("printer_ref", "material_ref", "profile_ref")]
        targets += [(conditions["orientation"]["value"], field) for field in ("frame", "description")]
        targets += [(self.observation["support_removal"], "description"),
                    (self.observation["fit_observation"], "description"),
                    (self.observation["fit_observation"]["target_ref"], "reason")]
        for owner, field in targets:
            for invalid in ("", " ", " padded ", None, False, 1, []):
                with self.subTest(field=field, invalid=invalid):
                    old = owner[field]
                    owner[field] = invalid
                    self.assert_input_error()
                    owner[field] = old

    def test_artifact_digest_must_be_exact_lowercase_sha256(self):
        for owner in (self.part, self.observation):
            for invalid in ("a" * 63, "a" * 65, "A" * 64, "g" * 64, " " + "a" * 64, "", None, True, 123):
                with self.subTest(digest=invalid):
                    old = owner["artifact_sha256"]
                    owner["artifact_sha256"] = invalid
                    self.assert_input_error()
                    owner["artifact_sha256"] = old

    def test_unknown_conditions_preserve_reasons_without_inventing_values(self):
        for field in self.observation["print_conditions"]:
            self.observation["print_conditions"][field] = {"status": "unknown", "reason": "Not recorded in synthetic input"}
        report, _ = self.evaluate()
        self.assertEqual(report["observation"]["print_conditions"], self.observation["print_conditions"])
        for condition in self.observation["print_conditions"].values():
            for invalid in ({"status": "unknown", "value": "guess"}, {"status": "unknown", "reason": ""},
                            {"status": "unknown", "reason": "unrecorded", "value": "guess"}):
                old = dict(condition)
                condition.clear()
                condition.update(invalid)
                self.assert_input_error()
                condition.clear()
                condition.update(old)

    def test_condition_tags_and_value_shapes_are_strict(self):
        owners = [(self.observation["print_conditions"], field) for field in self.observation["print_conditions"]]
        owners.append((self.observation["fit_observation"], "target_ref"))
        for owner, field in owners:
            old = copy.deepcopy(owner[field])
            for invalid in (None, "unknown", [], True, {}, {"status": "measured", "value": "x"},
                            {"status": "known"}, {"status": "known", "value": "x", "reason": "extra"}):
                with self.subTest(field=field, invalid=invalid):
                    owner[field] = invalid
                    self.assert_input_error()
            owner[field] = old
        for invalid in ("upright", [], None, {"frame": "plate"}, {"frame": "plate", "description": "up", "axis": "z"}):
            old = self.observation["print_conditions"]["orientation"]["value"]
            self.observation["print_conditions"]["orientation"]["value"] = invalid
            self.assert_input_error()
            self.observation["print_conditions"]["orientation"]["value"] = old

    def test_known_dimensions_are_strictly_positive_finite_json_numbers(self):
        for field in ("nozzle_diameter_mm", "layer_height_mm"):
            owner = self.observation["print_conditions"][field]
            for invalid in (0, -0.0, -0.1, True, False, "0.4", None, [], {}, float("nan"), float("inf"),
                            -float("inf"), 10 ** 101, 1e-101):
                with self.subTest(field=field, invalid=str(invalid)):
                    old = owner["value"]
                    owner["value"] = invalid
                    self.assert_input_error()
                    owner["value"] = old
        self.save()
        raw = self.paths[2].read_bytes().replace(b'"value": 0.4', b'"value": 0.40000000000000000001')
        self.paths[2].write_bytes(raw)
        report, _ = record_fabrication(*self.paths)
        self.assertEqual(report["observation"]["print_conditions"]["nozzle_diameter_mm"]["value"], "0.40000000000000000001")

    def test_supported_removal_and_fit_states_never_become_a_physical_judgment(self):
        for support in ("removed", "partial", "not_performed", "unknown"):
            for fit in ("assembled", "interference", "not_tested", "unknown"):
                with self.subTest(support=support, fit=fit):
                    self.observation["support_removal"]["status"] = support
                    self.observation["fit_observation"]["status"] = fit
                    self.observation["fit_observation"]["target_ref"] = {"status": "known", "value": "synthetic-mate-r1"}
                    report, _ = self.evaluate()
                    self.assertEqual(report["judgment"], "not_applicable")
                    self.assertEqual(report["physical_validation"], "not_performed")
                    self.assertFalse(report["printer_ready"])
        self.observation["process_state"] = "before_support_removal"
        self.observation["support_removal"]["status"] = "removed"
        self.assertEqual(self.evaluate()[0]["execution_status"], "complete")

    def test_attempted_fit_requires_known_target_but_unattempted_fit_can_be_unknown(self):
        for status in ("assembled", "interference"):
            self.observation["fit_observation"]["status"] = status
            self.assert_input_error()
            self.observation["fit_observation"]["target_ref"] = {"status": "known", "value": "synthetic-mate-r1"}
            self.assertEqual(self.evaluate()[0]["judgment"], "not_applicable")
            self.observation["fit_observation"]["target_ref"] = {"status": "unknown", "reason": "No target selected"}
        for status in ("not_tested", "unknown"):
            self.observation["fit_observation"]["status"] = status
            self.assertEqual(self.evaluate()[0]["execution_status"], "complete")

    def test_unsupported_sources_and_states_are_rejected(self):
        targets = ((self.observation, "source_kind"), (self.observation["support_removal"], "status"),
                   (self.observation["fit_observation"], "status"))
        for owner, field in targets:
            for invalid in ("pass", "human_measurement", "complete", "", None, True, [], {}):
                with self.subTest(field=field, invalid=invalid):
                    old = owner[field]
                    owner[field] = invalid
                    self.assert_input_error()
                    owner[field] = old

    def test_corrupt_duplicate_nonfinite_and_deep_json_are_rejected_for_each_input(self):
        invalid_json = (b'{', b'[]', b'null', b'\xff', b'{"schema_version":1,"schema_version":1}',
                        b'{"value":NaN}', b'{"value":Infinity}', b'{"value":-Infinity}',
                        b'{"value":1e309}', b'{"value":1e-999}',
                        b'{"value":1e9999999999999999999}', b'{"value":1e-9999999999999999999}',
                        b'{"value":' + b'1' * 129 + b'}',
                        b'[' * 1500 + b']' * 1500)
        self.save()
        for path in self.paths:
            old = path.read_bytes()
            for raw in invalid_json:
                with self.subTest(path=path.name, raw=raw[:30]):
                    path.write_bytes(raw)
                    self.assert_input_error(save=False)
            path.write_bytes(old)
        raw = self.paths[2].read_bytes().replace(b'"status": "partial"', b'"status": "partial", "status": "removed"')
        self.paths[2].write_bytes(raw)
        self.assert_input_error(save=False)

    def test_each_input_is_bounded_to_64_kib_including_whitespace(self):
        self.save()
        for path in self.paths:
            with self.subTest(path=path.name):
                original = path.read_bytes()
                padded = original + b" " * (64 * 1024 - len(original))
                path.write_bytes(padded)
                report, _ = record_fabrication(*self.paths)
                self.assertEqual(report["execution_status"], "complete")
                path.write_bytes(padded + b" ")
                self.assert_input_error(save=False)
                path.write_bytes(original)

    def test_nonregular_inputs_are_rejected_before_opening(self):
        self.save()
        original_stat = Path.stat
        for source in self.paths:
            resolved = source.resolve()
            for mode in (stat.S_IFIFO, stat.S_IFCHR, stat.S_IFSOCK, stat.S_IFDIR):
                def replaced_stat(path, *args, **kwargs):
                    if path == resolved:
                        return SimpleNamespace(st_mode=mode)
                    return original_stat(path, *args, **kwargs)
                with self.subTest(path=source.name, mode=mode), patch.object(Path, "stat", replaced_stat), \
                        patch("physical_ci.inspection.os.open", wraps=os.open) as opened:
                    self.assert_input_error(save=False)
                    self.assertFalse(any(Path(call.args[0]) == resolved for call in opened.call_args_list))

    def test_opened_input_descriptor_is_checked_and_closed_before_reading(self):
        self.save()
        original_fstat = os.fstat
        opened = []
        def replaced_fstat(descriptor):
            opened.append(descriptor)
            if len(opened) == 3:  # Subject and part are regular; replace the opened observation.
                return SimpleNamespace(st_mode=stat.S_IFIFO)
            return original_fstat(descriptor)
        with patch("physical_ci.inspection.os.fstat", replaced_fstat):
            self.assert_input_error(save=False)
        with self.assertRaises(OSError):
            original_fstat(opened[-1])

    def test_missing_input_is_an_execution_error_with_no_output(self):
        self.save()
        for path in self.paths:
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.unlink()
                code, report, explanation = self.run_cli(save=False)
                self.assertEqual(code, 1)
                self.assertEqual(report["execution_status"], "error")
                self.assertEqual(report["judgment"], "not_applicable")
                self.assertIn("execution error", explanation)
                self.assertFalse(self.output.exists())
                path.write_bytes(original)

    def test_fresh_output_is_required_and_all_inputs_are_protected(self):
        self.assertEqual(self.run_cli()[0], 0)
        existing = self.output.read_bytes()
        code, report, _ = self.run_cli()
        self.assertEqual(code, 2)
        self.assertEqual(report["judgment"], "not_applicable")
        self.assertEqual(self.output.read_bytes(), existing)
        self.output.unlink()
        for path in self.paths:
            self.output = path
            self.save()
            original = path.read_bytes()
            code, report, _ = self.run_cli(save=False)
            self.assertEqual(code, 2)
            self.assertEqual(report["judgment"], "not_applicable")
            self.assertEqual(path.read_bytes(), original)

    def test_invalid_filesystem_paths_produce_structured_errors(self):
        self.save()
        for index in range(len(self.paths)):
            old = self.paths[index]
            self.paths[index] = self.root / "bad\x00input"
            self.assert_input_error(save=False)
            self.paths[index] = old
        self.output = self.root / "bad\x00output"
        self.assert_input_error(save=False)

    def test_cli_requires_part_observation_and_output_without_flag_abbreviations(self):
        self.save()
        pairs = [("--part", str(self.paths[1])), ("--observation", str(self.paths[2])), ("--output", str(self.output))]
        invalid_arguments = [["record-fabrication", str(self.paths[0]),
                              *[item for index, pair in enumerate(pairs) if index != omitted for item in pair]]
                             for omitted in range(3)]
        invalid_arguments.append(["record-fabrication", str(self.paths[0]), "--pa", str(self.paths[1]),
                                  "--observation", str(self.paths[2]), "--output", str(self.output)])
        for args in invalid_arguments:
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    main(args)
                self.assertEqual(error.exception.code, 2)
                self.assertFalse(self.output.exists())

    def test_synthetic_sidecar_is_hash_bound_length_evidence_without_generating_measurements(self):
        code, fabrication, _ = self.run_cli()
        self.assertEqual(code, 0)
        sidecar_path = self.paths[2]
        sidecar_hash = hashlib.sha256(sidecar_path.read_bytes()).hexdigest()
        self.assertEqual(sidecar_hash, fabrication["input_hashes"]["observation_sha256"])
        requirement = {"schema_version": 1, "feature_id": "length-A", "requirement_revision": "independent-r1",
                       "unit": "mm", "process_state": "after_support_removal", "measurement_method": "caliper_length",
                       "tolerance": {"lower": 9.9, "upper": 10.1},
                       "judgment_policy": {"name": "interval_containment_v1", "unevaluated_uncertainty": "indeterminate"}}
        self.assertEqual(requirement["process_state"], self.observation["process_state"])
        measurement = {**self.subject, **{k: requirement[k] for k in
                       ("feature_id", "requirement_revision", "unit", "process_state", "measurement_method")},
                       "value": 10, "source_kind": "synthetic",
                       "uncertainty": {"status": "evaluated", "value": 0.01, "unit": "mm", "basis": "Synthetic half-width"},
                       "evidence_refs": [{"path": sidecar_path.name, "sha256": sidecar_hash}]}
        requirement_path, measurement_path = self.root / "requirement.json", self.root / "measurement.json"
        for path, data in ((requirement_path, requirement), (measurement_path, measurement)):
            path.write_bytes((json.dumps(data) + "\n").encode("utf-8"))
        before_requirement, before_measurement = requirement_path.read_bytes(), measurement_path.read_bytes()
        report, protected = inspect_length(self.paths[0], requirement_path, measurement_path)
        self.assertEqual(report["judgment"], "pass")
        self.assertEqual(report["evidence_class"], "record")
        self.assertTrue(report["synthetic"])
        self.assertEqual(report["subject"], fabrication["subject"])
        self.assertEqual(report["input_hashes"]["subject_sha256"], fabrication["input_hashes"]["subject_sha256"])
        for field in SUBJECT_FIELDS:
            self.assertEqual(report["measurement"][field], fabrication["subject"][field])
        self.assertEqual(report["input_hashes"]["requirement_sha256"], hashlib.sha256(before_requirement).hexdigest())
        self.assertEqual(report["input_hashes"]["measurement_sha256"], hashlib.sha256(before_measurement).hexdigest())
        self.assertEqual(report["measurement"]["process_state"], fabrication["observation"]["process_state"])
        self.assertEqual(report["verified_evidence_sha256"], [fabrication["input_hashes"]["observation_sha256"]])
        self.assertIn(sidecar_path.resolve(), protected)
        self.assertNotIn("fit_observation", report["measurement"])
        self.assertNotIn("print_conditions", report["measurement"])
        self.assertEqual(requirement_path.read_bytes(), before_requirement)
        self.assertEqual(measurement_path.read_bytes(), before_measurement)
        self.assertEqual(fabrication["judgment"], "not_applicable")
        absent, _ = inspect_length(self.paths[0], requirement_path)
        self.assertEqual(absent["reason"], "missing_measurement")
        self.assertEqual(absent["execution_status"], "not_run")
        self.assertEqual(absent["judgment"], "indeterminate")
        self.assertIsNone(absent["measurement"])
        sidecar_path.write_bytes(sidecar_path.read_bytes() + b"\n")
        with self.assertRaisesRegex(InputError, "evidence SHA256 mismatch"):
            inspect_length(self.paths[0], requirement_path, measurement_path)
        out, err = io.StringIO(), io.StringIO()
        length_output = self.root / "length-result.json"
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["inspect-length", str(self.paths[0]), "--requirement", str(requirement_path),
                         "--measurement", str(measurement_path), "--output", str(length_output)])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out.getvalue())["judgment"], "not_applicable")
        self.assertFalse(length_output.exists())


if __name__ == "__main__":
    unittest.main()
