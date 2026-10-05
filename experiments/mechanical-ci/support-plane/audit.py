"""Nominal support extrusion-plane to declared CAD underside distance.

The reported signed difference is between a command plane and a nominal CAD
plane. It is not a bead-surface air gap, contact state, or removal-force model.
"""
import argparse
import hashlib
import json
import math
from fractions import Fraction
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools/mechanical-ci/src"))
from physical_ci.cli import write_json
from physical_ci.errors import InputError
from physical_ci.gcode import extract
from physical_ci.manifest import keys, number
from physical_ci.support import SUPPORT_ROLES, screen_support
from physical_ci.tool import json_float, json_int, unique_object, reject_constant

MODEL_ROLES = frozenset(("Perimeter", "External perimeter", "Overhang perimeter", "Internal infill",
                         "Solid infill", "Top solid infill", "Bridge infill", "Internal bridge infill",
                         "Gap fill", "Ironing"))


def read_bounded(path, limit):
    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    if not raw or len(raw) > limit:
        raise InputError("input is empty or exceeds its byte limit")
    return raw


def load_plane(raw):
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                          parse_float=json_float, parse_int=json_int,
                          parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise InputError(f"invalid plane specification: {error}") from error
    keys(data, ("schema_version", "frame", "units", "gcode_sha256", "xy_min", "xy_max",
                "nominal_plane_z_mm", "boundary"), label="plane specification")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise InputError("plane schema_version must be integer 1")
    if data["frame"] != "gcode_machine_coordinates" or data["units"] != "mm":
        raise InputError("explicit gcode_machine_coordinates and mm required")
    if data["boundary"] != "closed":
        raise InputError("only closed XY windows are supported")
    for key in ("xy_min", "xy_max"):
        if not isinstance(data[key], list) or len(data[key]) != 2:
            raise InputError(f"{key} must contain two coordinates")
        for value in data[key]:
            number(value, key)
    if not all(a < b for a, b in zip(data["xy_min"], data["xy_max"])):
        raise InputError("XY min must be strictly below max")
    number(data["nominal_plane_z_mm"], "nominal_plane_z_mm")
    digest = data["gcode_sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise InputError("invalid G-code SHA256")
    return data


def xy_intersection(start, end, lower, upper):
    """Exact closed clipping of the parsed decimal-representable centerline.

    Width and bead cross-section are deliberately absent from this selection.
    """
    enter, leave = Fraction(0), Fraction(1)
    for origin, finish, lo, hi in zip(start[:2], end[:2], lower, upper):
        origin, finish, lo, hi = map(lambda x: Fraction(str(x)), (origin, finish, lo, hi))
        delta = finish - origin
        if delta == 0:
            if origin < lo or origin > hi:
                return None
            continue
        a, b = (lo - origin) / delta, (hi - origin) / delta
        enter, leave = max(enter, min(a, b)), min(leave, max(a, b))
        if enter > leave:
            return None
    return [float(enter), float(leave)]


def audit_bytes(raw_gcode, raw_plane):
    plane = load_plane(raw_plane)
    gcode_digest = hashlib.sha256(raw_gcode).hexdigest()
    if plane["gcode_sha256"] != gcode_digest:
        raise InputError("plane G-code SHA256 mismatch")
    stationary = []
    summary, segments = extract(raw_gcode.decode("utf-8"), stationary_events=stationary)
    # Reuse the existing conservative metadata/dialect coverage policy, but no
    # AABB hits or width/height envelope are used for this plane measurement.
    gaps = screen_support(summary, segments, stationary, [])["coverage_gaps"]
    for event in stationary:
        gaps.append({"line": event["line"], "role": event["role"],
                     "kind": "stationary_prime", "reasons": ["stationary_deposition_outside_moving_path_scope"]})
    selected = []
    model = []
    for segment in segments:
        start, end = segment["from_mm"], segment["to_mm"]
        if start[2] != end[2]:
            continue
        interval = xy_intersection(start, end, plane["xy_min"], plane["xy_max"])
        if interval is None:
            continue
        witness = {"line": segment["line"], "role": segment["role"], "z_mm": end[2],
                   "from_mm": start, "to_mm": end, "xy_clip_interval": interval,
                   "width_metadata_mm": segment["width_mm"], "height_metadata_mm": segment["height_mm"]}
        if segment["role"] in SUPPORT_ROLES:
            selected.append(witness)
        elif segment["role"] in MODEL_ROLES and end[2] >= plane["nominal_plane_z_mm"]:
            model.append(witness)
    known_top = max((event["z_mm"] for event in selected), default=None)
    complete = not gaps
    distance = None
    if complete and known_top is not None:
        distance = plane["nominal_plane_z_mm"] - known_top
        if not math.isfinite(distance):
            raise InputError("nominal plane difference arithmetic overflow")
    first_model_z = min((event["z_mm"] for event in model), default=None)
    return {"schema_version": 1, "experiment": "nominal_support_extrusion_plane_to_CAD_underside_distance",
            "gcode_sha256": gcode_digest, "plane_specification_sha256": hashlib.sha256(raw_plane).hexdigest(),
            "hash_scope": "the exact byte buffers parsed; no claim that live input paths remained unchanged",
            "frame": "gcode_machine_coordinates", "units": "mm", "window": plane,
            "selection": "planar positive moving-support-extrusion centerline intersects closed XY window; no width expansion",
            "coverage_complete": complete, "coverage_gaps": sorted(gaps, key=lambda e: e["line"]),
            "selected_support_events": len(selected),
            "known_selected_top_z_mm": known_top,
            "nominal_plane_minus_top_mm": distance,
            "known_selected_planes_mm": sorted({event["z_mm"] for event in selected}),
            "top_witnesses": [event for event in selected if event["z_mm"] == known_top],
            "known_first_model_plane_at_or_above_nominal_z_mm": first_model_z,
            "known_first_model_plane_witnesses": [event for event in model if event["z_mm"] == first_model_z],
            "model_plane_observation_scope": "known model-role centerlines only; not guaranteed the first actual layer when coverage is incomplete",
            "outcome": "incomplete" if not complete else "measured" if selected else "no_support_observed_in_window",
            "physical_air_gap": "not_measured", "physical_contact": "not_evaluated",
            "removal_force": "not_evaluated", "physical_validation": "not_performed",
            "limits": [
                "The signed difference uses a nominal CAD plane and G-code support command Z, not actual bead surfaces.",
                "A negative difference is retained; it is not automatically a physical interference diagnosis.",
                "Bridge HEIGHT metadata does not define a physical underside or actual contact gap.",
                "The inherited parser covers a limited linear single-extruder dialect and floating-point arithmetic.",
                "Unknown roles, missing width/height, nonplanar and all stationary deposition leave conservative coverage incomplete.",
                "Known observations remain available when coverage is incomplete; the final plane difference is withheld.",
                "No support strength, adhesion, removal force, print dimensional accuracy or successful removal is inferred.",
            ]}


def audit(gcode, plane):
    return audit_bytes(read_bounded(gcode, 64 * 1024 * 1024), read_bounded(plane, 64 * 1024))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gcode", type=Path)
    parser.add_argument("--plane", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    result = audit(args.gcode, args.plane)
    write_json(args.output, result, [args.gcode, args.plane])


if __name__ == "__main__":
    main()
