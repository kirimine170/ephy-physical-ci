"""Experimental conjunction of two declared coaxial cylindrical sweeps.

No new geometry classifier: each component uses physical_ci.tool unchanged.
The declared envelope need not contain the real handle, gripper or hand.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools/mechanical-ci/src"))
from physical_ci.errors import InputError
from physical_ci.manifest import keys, number, vector
from physical_ci.tool import (
    AXIS_NORM_EPSILON, ENDPOINT_REL_EPSILON, MAX_SPEC_BYTES,
    consistent_endpoint, json_float, json_int, load_tool_spec, reject_constant,
    resolved_offset, screen_tool, step_snapshot, unique_object,
)


def component_tip(motion, component, epsilon):
    """Check relative vectors, not only a roundtrip at a large global origin."""
    tip, travel = motion["tip_mm"], motion["travel_mm"]
    norm = math.hypot(*motion["axis"])
    axis = [v / norm for v in motion["axis"]]
    backset = component["backset_mm"]
    dimensions = [component["length_mm"], component["radius_mm"]]
    dimensions += [v for v in (backset, travel) if v > 0]
    tolerance = min(epsilon, ENDPOINT_REL_EPSILON * min(dimensions))
    local_tip = resolved_offset(tip, [-d for d in axis], backset, "component backset")
    end = resolved_offset(tip, axis, travel, "reference travel")
    local_end = resolved_offset(local_tip, axis, travel, "component travel")

    def relative_matches(start, finish, expected, label):
        observed = [b - a for a, b in zip(start, finish)]
        error = math.dist(observed, expected)
        if not math.isfinite(error) or error > tolerance:
            raise InputError(f"{label} disagrees with the declared relative displacement")

    expected_backset = [d * backset for d in axis]
    relative_matches(local_tip, tip, expected_backset, "initial component backset")
    relative_matches(local_end, end, expected_backset, "final component backset")
    expected_travel = [d * travel for d in axis]
    relative_matches(tip, end, expected_travel, "reference travel")
    relative_matches(local_tip, local_end, expected_travel, "component travel")
    consistent_endpoint(local_tip, axis, backset, tip, tolerance, "component reference tip")
    return local_tip


def load(path):
    path = Path(path).resolve()
    with path.open("rb") as stream:
        raw = stream.read(MAX_SPEC_BYTES + 1)
    if len(raw) > MAX_SPEC_BYTES:
        raise InputError("assembly specification exceeds 64 KiB")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                          parse_float=json_float, parse_int=json_int,
                          parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise InputError(f"invalid assembly specification: {error}") from error
    keys(data, ("schema_version", "units", "frame", "obstacle", "motion",
                "components", "numeric_epsilon_mm", "numeric_epsilon_mm3"),
         label="assembly specification")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise InputError("assembly schema_version must be integer 1")
    if data["units"] != "mm" or data["frame"] != "assembly":
        raise InputError("explicit mm and assembly frame required")
    obstacle = data["obstacle"]
    keys(obstacle, ("path", "sha256", "frame"), label="obstacle")
    name, digest = obstacle["path"], obstacle["sha256"]
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise InputError("relative POSIX STEP path required")
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise InputError("obstacle path must remain inside specification directory")
    source = (path.parent / name).resolve()
    if (not source.is_relative_to(path.parent) or not source.is_file()
            or source.suffix.lower() not in (".step", ".stp")
            or obstacle["frame"] != "assembly"):
        raise InputError("obstacle must be an in-root assembly STEP")
    if (not isinstance(digest, str) or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)):
        raise InputError("invalid obstacle SHA256")
    motion = data["motion"]
    keys(motion, ("tip_mm", "axis", "travel_mm"), label="motion")
    tip = vector(motion["tip_mm"], "tip_mm")
    declared_axis = vector(motion["axis"], "axis")
    norm = math.hypot(*declared_axis)
    if not math.isclose(norm, 1., rel_tol=0., abs_tol=AXIS_NORM_EPSILON):
        raise InputError("axis must be a unit vector")
    axis = [v / norm for v in declared_axis]
    number(motion["travel_mm"], "travel_mm", nonnegative=True)
    epsilon = number(data["numeric_epsilon_mm"], "numeric_epsilon_mm", positive=True)
    number(data["numeric_epsilon_mm3"], "numeric_epsilon_mm3", positive=True)
    components = data["components"]
    if not isinstance(components, list) or len(components) != 2:
        raise InputError("this experiment requires exactly two declared cylinders")
    identifiers = set()
    for component in components:
        keys(component, ("id", "backset_mm", "length_mm", "radius_mm"), label="component")
        identifier = component["id"]
        if (not isinstance(identifier, str) or not identifier or len(identifier) > 64
                or identifier in identifiers):
            raise InputError("component ids must be nonempty unique strings of at most 64 characters")
        identifiers.add(identifier)
        backset = number(component["backset_mm"], "backset_mm", nonnegative=True)
        length = number(component["length_mm"], "length_mm", positive=True)
        radius = number(component["radius_mm"], "radius_mm", positive=True)
        component_tip(motion, component, epsilon)
    return data, source, hashlib.sha256(raw).hexdigest()


def aggregate(reports):
    """Preserve any known blocker, but never turn incomplete evidence into clear."""
    if len(reports) != 2:
        raise InputError("exactly two component reports required")
    outcomes = []
    for report in reports:
        metrics = (report["intersection_mm3"], report["minimum_distance_mm"])
        valid = all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in metrics)
        outcomes.append(report["outcome"] if valid else "indeterminate")
    complete = all(o in ("model_clear", "interference") for o in outcomes)
    if "interference" in outcomes:
        outcome = "interference"
    elif all(o == "model_clear" for o in outcomes):
        outcome = "model_clear"
    else:
        outcome = "indeterminate"
    # Incomplete/contact evidence gets no aggregate clearance number, even if
    # a kernel reported a finite distance before a different operation failed.
    distances = [r["minimum_distance_mm"] for r in reports]
    valid_distances = all(type(d) in (int, float) and math.isfinite(d) and d >= 0 for d in distances)
    minimum = min(distances) if complete and valid_distances else None
    return {"outcome": outcome, "coverage_complete": complete,
            "model_clear": outcome == "model_clear", "minimum_distance_mm": minimum,
            "blocking_components": [r["component"]["id"] for r, o in zip(reports, outcomes) if o == "interference"],
            "indeterminate_components": [r["component"]["id"] for r, o in zip(reports, outcomes) if o not in ("model_clear", "interference")]}


def screen(path):
    data, source, digest = load(path)
    motion = data["motion"]
    norm = math.hypot(*motion["axis"])
    axis = [v / norm for v in motion["axis"]]
    reports = []
    # One live read only. Both existing screen-tool invocations read the same
    # bounded snapshot, and the outer context checks its bytes before return.
    with step_snapshot(source, data["obstacle"]["sha256"]) as (snapshot, step_digest):
        for index, component in enumerate(data["components"]):
            local_tip = component_tip(motion, component, data["numeric_epsilon_mm"])
            canonical = {"schema_version": 1, "units": "mm", "frame": "assembly",
                         "obstacle": {"path": snapshot.name, "sha256": step_digest, "frame": "assembly"},
                         "tool": {"kind": "flat_end_cylinder", "tip_mm": local_tip,
                                  "axis": motion["axis"], "travel_mm": motion["travel_mm"],
                                  "radius_mm": component["radius_mm"], "length_mm": component["length_mm"]},
                         "numeric_epsilon_mm": data["numeric_epsilon_mm"],
                         "numeric_epsilon_mm3": data["numeric_epsilon_mm3"]}
            component_path = snapshot.parent / f"component-{index}.json"
            component_path.write_text(json.dumps(canonical, sort_keys=True) + "\n", encoding="utf-8")
            spec, frozen_source, spec_digest = load_tool_spec(component_path)
            report = screen_tool(spec, frozen_source, spec_digest)
            report["component"] = component
            report["canonical_specification"] = canonical
            reports.append(report)
    return {"schema_version": 1, "experiment": "two_coaxial_cylinders",
            "specification_sha256": digest, "step_sha256": step_digest,
            "same_snapshot_for_all_components": True,
            "motion": motion, "components": reports, **aggregate(reports),
            "union_intersection_volume_mm3": None,
            "full_tool_assembly_verified": False, "physical_validation": "not_performed",
            "support_removal": "not_implemented", "removal_force": "not_implemented",
            "limits": [
                "Only the two declared flat-ended coaxial cylinders and one forward axial translation are modeled.",
                "Backsets and radii are independent; omitted gaps, handles, hands and attachments are not inferred.",
                "Model-clear requires both component sweeps to be clear against the same frozen obstacle bytes.",
                "Known interference is retained when another component is indeterminate; coverage stays incomplete.",
                "Component sweep overlap volumes must not be summed as a union volume.",
                "Numerical epsilons are not printing, manufacturing or physical clearance tolerances.",
                "No path search, bending, lateral motion, rotation, support fracture or successful removal is certified.",
                "Snapshot identity does not assert that the original live file remained unchanged.",
            ]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("specification", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        parser.error("output must be a new file; existing inputs/reports cannot be overwritten")
    result = screen(args.specification)
    raw = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(raw)


if __name__ == "__main__":
    main()
