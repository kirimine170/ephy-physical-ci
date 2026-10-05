"""Four pinned synthetic slices; no printer connection or physical gap claim."""
import argparse
from decimal import Decimal as D
import hashlib
import json
import math
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys

from audit import ROOT, audit
from physical_ci.manifest import load_manifest
from physical_ci.slicer import inspect_profile, run_slicer

HERE = Path(__file__).resolve().parent
BASE_COMMIT = "a169ce162d453835d8377f73abb7cec0bb82bdff"
SLICER_SHA256 = "7beaf8cc8861dcb97803da73222bdee358992e02c13a8e2b6212ae4809c121d2"
FIXED = {"layer_height": "0.2", "first_layer_height": "0.2", "nozzle_diameter": "0.4",
         "bridge_flow_ratio": "1", "thick_bridges": "1", "support_material_style": "grid",
         "support_material_synchronize_layers": "0", "z_offset": "0"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def public_decimal_auditor():
    # Reuse the independently written public E2E modal scanner, not the product
    # gcode parser. Its M83-only precondition is explicitly checked per event.
    source = ROOT / "experiments/mechanical-ci/support-screen-e2e/run_e2e.py"
    # run_path executes definitions without writing __pycache__ into the frozen
    # historical artifact directory. Its default name does not invoke main().
    return runpy.run_path(str(source))["audit"]


def crosses_window(event):
    """Decimal orientation/edge-intersection oracle, separate from slab clipping."""
    lo, hi = (D(85), D(84)), (D(95), D(96))
    a, b = event["start"][:2], event["end"][:2]
    if any(all(l <= v <= h for l, v, h in zip(lo, point, hi)) for point in (a, b)):
        return True

    def turn(p, q, r):
        return (q[0]-p[0])*(r[1]-p[1]) - (q[1]-p[1])*(r[0]-p[0])

    def between(p, q, r):
        return all(min(x, y) <= z <= max(x, y) for x, y, z in zip(p, q, r))

    corners = [lo, (hi[0], lo[1]), hi, (lo[0], hi[1])]
    for c, d in zip(corners, corners[1:] + corners[:1]):
        turns = turn(a, b, c), turn(a, b, d), turn(c, d, a), turn(c, d, b)
        if turns[0]*turns[1] < 0 and turns[2]*turns[3] < 0:
            return True
        for value, p, q, r in ((turns[0], a, b, c), (turns[1], a, b, d),
                               (turns[2], c, d, a), (turns[3], c, d, b)):
            if value == 0 and between(p, q, r):
                return True
    return False


def pose_gate(events):
    observations = {}
    for name, zlo, zhi, xhi in (("base", D(".4"), D("1.8"), D(105)),
                                ("wall", D(4), D(10), D(78))):
        feature = [e for e in events if e["role"] == "External perimeter" and zlo <= e["end"][2] <= zhi]
        assert feature, f"missing {name} pose landmark"
        assert all(e["width"] is not None and e["width"] <= D(".6") for e in feature)
        extrema = []
        for axis, lower, upper in ((0, D(75), xhi), (1, D(80), D(100))):
            values = [point[axis] for e in feature for point in (e["start"], e["end"])]
            assert abs(min(values)-lower) < D(".6") and abs(max(values)-upper) < D(".6"), name
            assert all(lower-D(".6") <= value <= upper+D(".6") for value in values), name
            extrema.append([float(min(values)), float(max(values))])
        observations[name] = {"events": len(feature), "xy_extrema_mm": extrema}
    return observations


def resolved_settings(text):
    settings = {}
    for raw in text.splitlines():
        match = re.fullmatch(r"; ([a-z_]+) = (.*)", raw)
        if match:
            settings[match[1]] = match[2]
    return settings


def reproduce(slicer, output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    slicer = Path(slicer).resolve()
    binary_digest = sha(slicer)
    if binary_digest != SLICER_SHA256:
        raise ValueError("This reproduction is pinned to the recorded Debian PrusaSlicer binary SHA256")
    help_result = subprocess.run([str(slicer), "--help"], capture_output=True, text=True, check=True, timeout=20)
    header = (help_result.stdout + help_result.stderr).splitlines()[0]
    assert re.match(r"PrusaSlicer-2\.9\.2(?:\+|\s|$)", header), header
    source_inputs = ROOT / "experiments/mechanical-ci/support-screen-e2e/run-003/inputs"
    inputs = output / "inputs"
    inputs.mkdir()
    shutil.copyfile(source_inputs / "shelf.stl", inputs / "shelf.stl")
    original = inspect_profile(source_inputs / "profile.ini")
    profiles = []
    for gap in ("0", "0.1", "0.2", "0.3"):
        values = {**original, **FIXED, "support_material_contact_distance": gap}
        profile = inputs / f"contact-{gap}.ini"
        profile.write_text("# ORIGINAL SYNTHETIC ANALYSIS ONLY. DO NOT PRINT.\n" +
                           "\n".join(f"{k} = {v}" for k, v in sorted(values.items())) + "\n")
        manifest = {"schema_version": 1, "name": f"contact-{gap}", "units": "mm",
                    "assembly_to_print": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],
                    "artifacts": {"print_mesh": {"path": "shelf.stl", "sha256": sha(inputs / "shelf.stl"), "frame": "print"},
                                  "profile": {"path": profile.name, "sha256": sha(profile), "frame": "configuration"}},
                    "slicing": {"engine": "PrusaSlicer", "expected_version": "2.9.2", "center_mm": [90,90], "support_mode": "auto"}}
        path = inputs / f"contact-{gap}.json"
        write(path, manifest)
        profiles.append((gap, path))
    profile_settings = [inspect_profile(inputs / f"contact-{gap}.ini") for gap, _ in profiles]
    stripped_settings = [{k: v for k, v in values.items() if k != "support_material_contact_distance"}
                         for values in profile_settings]
    assert all(values == stripped_settings[0] for values in stripped_settings)
    plan = json.loads((HERE / "oracles/slicer-study-plan.json").read_text())
    write(output / "preregistered.json", plan)
    write(output / "provenance.json", {"base_commit": BASE_COMMIT, "slicer_header": header,
          "slicer_sha256": binary_digest, "binary_distribution": "existing official Debian stable PrusaSlicer 2.9.2+dfsg-1 package",
          "python": sys.version.split()[0], "source_sha256": {
              str(p.relative_to(ROOT)): sha(p) for p in [HERE / "audit.py", HERE / "reproduce.py",
                  ROOT / "tools/mechanical-ci/src/physical_ci/gcode.py", ROOT / "tools/mechanical-ci/src/physical_ci/support.py",
                  ROOT / "tools/mechanical-ci/src/physical_ci/slicer.py",
                  ROOT / "experiments/mechanical-ci/support-screen-e2e/run_e2e.py"]},
          "fixture_sha256": sha(inputs / "shelf.stl"), "profiles": {p.name: sha(p) for p in inputs.glob("*.ini")}})
    parse_decimal = public_decimal_auditor()
    observations = []
    for gap, path in profiles:
        case = output / f"contact-{gap}"
        manifest, paths, digest = load_manifest(path)
        summary, _ = run_slicer(manifest, paths, digest, str(slicer), case)
        write(case / "slice-summary.json", summary)
        gcode = case / "toolpath.analysis-only.gcode"
        before = sha(gcode)
        text = gcode.read_text()
        resolved = resolved_settings(text)
        for key, expected in {**FIXED, "support_material_contact_distance": gap}.items():
            if key == "support_material_style":
                assert resolved[key] == expected, (key, resolved.get(key), expected)
            else:
                assert D(resolved[key]) == D(expected), (key, resolved.get(key), expected)
        events = parse_decimal(text)
        pose = pose_gate(events)
        chosen = [e for e in events if e["role"] in ("Support material", "Support material interface")
                  and e["start"][2] == e["end"][2] and crosses_window(e)]
        assert chosen, "fixed window has no independent support observation"
        top = max(e["end"][2] for e in chosen)
        plane = {"schema_version": 1, "frame": "gcode_machine_coordinates", "units": "mm",
                 "gcode_sha256": before, "xy_min": [85,84], "xy_max": [95,96],
                 "nominal_plane_z_mm": 12, "boundary": "closed"}
        plane_path = case / "plane.json"
        write(plane_path, plane)
        report = audit(gcode, plane_path)
        assert report["coverage_complete"], report["coverage_gaps"]
        assert math.isclose(report["known_selected_top_z_mm"], float(top), abs_tol=1e-9)
        expected_lines = {e["line"] for e in chosen if e["end"][2] == top}
        assert expected_lines == {e["line"] for e in report["top_witnesses"]}
        write(case / "plane-report.json", report)
        assert before == sha(gcode), "G-code bytes differ at before/after observations"
        model_witnesses = report["known_first_model_plane_witnesses"]
        model = {"known_first_z_mm": report["known_first_model_plane_at_or_above_nominal_z_mm"],
                 "roles": sorted({e["role"] for e in model_witnesses}),
                 "height_metadata_mm": sorted({e["height_metadata_mm"] for e in model_witnesses})}
        prediction = next((v for v in plan["conditional_predictions"] if D(str(v["configured_gap_mm"])) == D(gap)), None)
        conditions_verified = (model["known_first_z_mm"] == 12.2
                               and model["roles"] == ["Bridge infill"]
                               and model["height_metadata_mm"] == [.4])
        prediction_matches = (None if prediction is None or not conditions_verified else
                              math.isclose(float(top), prediction["support_plane_z_mm"], abs_tol=1e-9))
        observations.append({"configured_contact_distance_mm": float(gap), "known_selected_support_plane_z_mm": float(top),
            "nominal_CAD_plane_minus_support_plane_mm": float(D(12)-top), "coverage_complete": report["coverage_complete"],
            "independent_top_witness_lines": sorted(expected_lines), "pose_gate": pose, "known_model_plane": model,
            "resolved_fixed_settings": {k: resolved[k] for k in FIXED},
            "conditional_prediction_conditions_verified": conditions_verified if prediction is not None else None,
            "conditional_prediction_matches": prediction_matches,
            "gcode_sha256": before, "gcode_before_after_equal": True,
            "report_sha256": sha(case / "plane-report.json")})
    assert binary_digest == sha(slicer), "binary hash changed during this run"
    result = {"experiment": plan["name"], "base_commit": BASE_COMMIT, "observations": observations,
              "independent_raw_audit_passed": True, "physical_air_gap_measured": False,
              "profile_settings_identical_except_contact_distance": True,
              "physical_validation": "not_performed",
              "note": "Configured contact distance and the nominal CAD-to-command-plane difference need not be equal; zero is a separate slicing regime."}
    write(output / "summary.json", result)
    write(output / "manifest.json", {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob("*"))
                                     if p.is_file() and p.name != "slicer.local.log"})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slicer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(reproduce(args.slicer, args.output), indent=2))
