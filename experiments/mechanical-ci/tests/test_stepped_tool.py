"""Independent scalar oracles and fail-closed composition regression tests."""
import contextlib
import copy
import importlib.util
import io
import itertools
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

EXPERIMENT = Path(__file__).resolve().parents[1] / "stepped-tool"
sys.path.insert(0, str(EXPERIMENT))
import screen as stepped
from reproduce import audit, build_bore, expected, sha, specification, write
from physical_ci.errors import InputError

HAVE_CADQUERY = importlib.util.find_spec("cadquery") is not None


def stub(outcome, identifier):
    return {"outcome": outcome, "intersection_mm3": 1 if outcome == "interference" else 0,
            "minimum_distance_mm": .5 if outcome == "model_clear" else 0,
            "component": {"id": identifier}}


class AggregationTests(unittest.TestCase):
    def test_all_nine_outcome_pairs(self):
        for pair in itertools.product(("model_clear", "interference", "indeterminate"), repeat=2):
            with self.subTest(pair=pair):
                result = stepped.aggregate([stub(pair[0], "tip"), stub(pair[1], "handle")])
                wanted = ("interference" if "interference" in pair else
                          "model_clear" if pair == ("model_clear", "model_clear") else "indeterminate")
                self.assertEqual(result["outcome"], wanted)
                self.assertEqual(result["coverage_complete"], "indeterminate" not in pair)
                if "indeterminate" in pair:
                    self.assertIsNone(result["minimum_distance_mm"])

    def test_nonfinite_or_missing_metrics_cannot_complete_clear(self):
        for metric in (None, float("nan"), float("inf"), -1, True):
            for field in ("intersection_mm3", "minimum_distance_mm"):
                bad = stub("model_clear", "handle")
                bad[field] = metric
                result = stepped.aggregate([stub("model_clear", "tip"), bad])
                self.assertEqual(result["outcome"], "indeterminate")
                self.assertFalse(result["coverage_complete"])
                blocked = stepped.aggregate([stub("interference", "tip"), bad])
                self.assertEqual(blocked["outcome"], "interference")
                self.assertEqual(blocked["blocking_components"], ["tip"])

    def test_no_empty_or_partial_assembly_clear(self):
        for reports in ([], [stub("model_clear", "tip")]):
            with self.assertRaises(InputError):
                stepped.aggregate(reports)


class InputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.step = self.root / "synthetic.step"
        self.step.write_bytes(b"not CAD: schema and snapshot IO fixture only\n")
        self.path = self.root / "input.json"
        self.data = specification(self.step, 4)

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        write(self.path, self.data)
        return self.path

    def test_independent_component_offsets_and_radii(self):
        self.data["components"][1].update(backset_mm=4.5, length_mm=2.25, radius_mm=3.5)
        data, _, _ = stepped.load(self.save())
        self.assertEqual(stepped.component_tip(data["motion"], data["components"][1], 1e-7), [0, 0, -5.5])

    def test_schema_unknown_keys_units_frame_cardinality_and_identifiers(self):
        mutations = [lambda d: d.update(units="inch"), lambda d: d.update(frame="machine"),
                     lambda d: d.update(schema_version=True), lambda d: d.update(extra=1),
                     lambda d: d.update(components=[]), lambda d: d["components"].pop(),
                     lambda d: d["components"][1].update(id="tip"),
                     lambda d: d["components"][0].update(id=""),
                     lambda d: d["components"][0].update(transform=[]),
                     lambda d: d["motion"].update(axis=[0, 0, 2])]
        for change in mutations:
            with self.subTest(change=change):
                self.data = specification(self.step, 4)
                change(self.data)
                with self.assertRaises(InputError):
                    stepped.load(self.save())

    def test_negative_nonfinite_bool_component_fields(self):
        for field in ("radius_mm", "length_mm", "backset_mm"):
            for value in (-1, True, float("nan"), float("inf"), "2"):
                with self.subTest(field=field, value=value):
                    self.data = specification(self.step, 4)
                    self.data["components"][0][field] = value
                    self.path.write_text(json.dumps(self.data))
                    with self.assertRaises(InputError):
                        stepped.load(self.path)

    def test_json_duplicate_and_underflow_are_rejected(self):
        raw = json.dumps(self.data)
        for broken in (raw.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'),
                       raw.replace('"backset_mm": 0', '"backset_mm": 1e-999')):
            self.path.write_text(broken)
            with self.assertRaises(InputError):
                stepped.load(self.path)

    def test_path_escape_and_hash_mismatch(self):
        for value in ("../synthetic.step", "/synthetic.step", "C:synthetic.step", "a\\synthetic.step"):
            self.data["obstacle"]["path"] = value
            with self.assertRaises(InputError):
                stepped.load(self.save())
        self.data = specification(self.step, 4)
        self.data["obstacle"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(InputError, "SHA256 mismatch"):
            stepped.screen(self.save())

    def test_initial_roundtrip_can_hide_backset_error(self):
        # (1e16 - 3) + 3 rounds back to 1e16, although actual separation is 4.
        for origin, axis in ((1e16, [1, 0, 0]), (-1e16, [-1, 0, 0])):
            self.data = specification(self.step, 2, [origin, 0, 0], axis)
            self.data["components"][1].update(backset_mm=3, length_mm=2, radius_mm=2)
            with self.assertRaisesRegex(InputError, "relative displacement"):
                stepped.load(self.save())

    def test_final_common_motion_cannot_lose_backset(self):
        self.data = specification(self.step, 1e16, [0, 0, 0], [1, 0, 0])
        self.data["components"][0].update(length_mm=10, radius_mm=2)
        self.data["components"][1].update(backset_mm=1, length_mm=10, radius_mm=2)
        with self.assertRaisesRegex(InputError, "final component backset"):
            stepped.load(self.save())

    def test_regular_oblique_and_zero_backset_remain_valid(self):
        axis = [1 / math.sqrt(3)] * 3
        self.data = specification(self.step, 4, [10, -7, 5], axis)
        stepped.load(self.save())
        self.data["motion"]["travel_mm"] = 0
        stepped.load(self.save())

    def test_one_snapshot_survives_live_input_change(self):
        original = self.step.read_bytes()
        received = []

        def fake(spec, source, digest):
            received.append(Path(source).read_bytes())
            self.step.write_bytes(b"live file changed after snapshot")
            result = stub("model_clear", "unused")
            result["input"] = {"step_sha256": spec["obstacle_sha256"]}
            return result

        with patch.object(stepped, "screen_tool", side_effect=fake):
            result = stepped.screen(self.save())
        self.assertEqual(received, [original, original])
        self.assertTrue(result["same_snapshot_for_all_components"])
        self.assertNotEqual(sha(self.step), result["step_sha256"])

    def test_snapshot_mutation_aborts_without_clear_report(self):
        def corrupt(spec, source, digest):
            Path(source).write_bytes(b"snapshot unexpectedly changed")
            return stub("model_clear", "unused")
        with patch.object(stepped, "screen_tool", side_effect=corrupt):
            with self.assertRaises(InputError):
                stepped.screen(self.save())

    def test_existing_output_and_input_alias_cannot_be_overwritten(self):
        self.save()
        report = self.root / "existing.json"
        report.write_text("previous result")
        for output in (report, self.path, self.step):
            original = output.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                stepped.main([str(self.path), "--output", str(output)])
            self.assertEqual(output.read_bytes(), original)

    def test_racing_output_creation_is_exclusive(self):
        self.save()
        output = self.root / "result.json"

        def racing(_):
            output.write_text("created by another writer")
            return {"outcome": "model_clear"}

        with patch.object(stepped, "screen", side_effect=racing), self.assertRaises(FileExistsError):
            stepped.main([str(self.path), "--output", str(output)])
        self.assertEqual(output.read_text(), "created by another writer")


@unittest.skipUnless(HAVE_CADQUERY, "CadQuery geometry extra is required for real kernel oracles")
class KernelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.step = self.root / "bore.step"
        build_bore(self.step)

    def tearDown(self):
        self.temp.cleanup()

    def run_case(self, data):
        path = self.root / "assembly.json"
        write(path, data)
        return stepped.screen(path)

    def test_tip_clear_but_handle_clear_contact_or_blocked(self):
        for travel in (2.5, 3, 4):
            with self.subTest(travel=travel):
                result = self.run_case(specification(self.step, travel))
                self.assertTrue(all(audit(result, expected(travel)).values()))
                self.assertFalse(result["full_tool_assembly_verified"])

    def test_rigid_rotation_translation_preserves_scalar_oracles(self):
        build_bore(self.step, transform=True)
        for travel in (2.5, 3, 4):
            result = self.run_case(specification(self.step, travel, [10, -7, 5], [1, 0, 0]))
            self.assertTrue(all(audit(result, expected(travel)).values()))

    def test_zero_travel_has_initial_pose_only(self):
        result = self.run_case(specification(self.step, 0))
        self.assertEqual(result["outcome"], "model_clear")
        # Tip top is 1 mm below the slab and 1 mm inside the bore rim.
        # The nearest point is diagonal to that rim, not directly overhead.
        self.assertAlmostEqual(result["minimum_distance_mm"], math.sqrt(2))

    def test_partial_handle_contact_band_never_becomes_clear(self):
        # Analytic positive overlap: 2.75*pi*1e-4, deliberately below
        # the declared decision threshold. The kernel has a resolvable slab.
        data = specification(self.step, 3.0001)
        data["numeric_epsilon_mm3"] = .01
        result = self.run_case(data)
        self.assertGreater(result["components"][1]["intersection_mm3"], 0)
        self.assertEqual(result["outcome"], "indeterminate")
        self.assertFalse(result["model_clear"])

    def test_changed_backset_changes_reach_without_enlarging_tip(self):
        data = specification(self.step, 4)
        data["components"][1]["backset_mm"] = 4
        result = self.run_case(data)
        self.assertEqual(result["outcome"], "model_clear")
        self.assertAlmostEqual(result["minimum_distance_mm"], 1.)


class RecordedEvidenceTests(unittest.TestCase):
    def test_independent_review_is_bound_to_exact_source(self):
        review = EXPERIMENT / "review"
        record = json.loads((review / "result.json").read_text())
        self.assertEqual(record["reviewed_screen_sha256"], sha(EXPERIMENT / "screen.py"))
        self.assertEqual(record["review_script_sha256"], sha(review / "verify.py"))
        self.assertTrue(record["all_19_controls_passed"])
        self.assertEqual(len(record["controls"]), 19)

    def test_recorded_bytes_and_source_identity(self):
        results = EXPERIMENT / "results"
        manifest = json.loads((results / "manifest.json").read_text())
        self.assertEqual(set(manifest), {p.name for p in results.iterdir() if p.name != "manifest.json"})
        for name, digest in manifest.items():
            self.assertEqual(sha(results / name), digest, name)
        summary = json.loads((results / "summary.json").read_text())
        for name, digest in summary["source_sha256"].items():
            self.assertEqual(sha(stepped.ROOT / name), digest, name)
        self.assertTrue(summary["passed"])
        self.assertEqual(len(summary["cases"]), 6)

    def test_recorded_full_reports_match_inputs_and_independent_oracles(self):
        results = EXPERIMENT / "results"
        for pose in ("original", "rigid_transform"):
            for travel in (2.5, 3, 4):
                name = f"{pose}-{travel}"
                spec_path = results / f"{name}.json"
                report = json.loads((results / f"{name}.report.json").read_text())
                self.assertEqual(report["specification_sha256"], sha(spec_path))
                self.assertEqual(report["step_sha256"], sha(results / f"{pose}.step"))
                self.assertTrue(all(audit(report, expected(travel)).values()))
                for component in report["components"]:
                    canonical = json.dumps(component["canonical_specification"], sort_keys=True) + "\n"
                    self.assertEqual(stepped.hashlib.sha256(canonical.encode()).hexdigest(),
                                     component["manifest_sha256"])
                self.assertFalse(report["full_tool_assembly_verified"])
                self.assertEqual(report["physical_validation"], "not_performed")


if __name__ == "__main__":
    unittest.main()
