"""Screen nominal support paths against explicitly located protected AABBs.

The envelope proxy is not deposited bead geometry or a removal/strength model.
"""
import hashlib
import json
import math
from fractions import Fraction
from pathlib import Path

from . import UNIMPLEMENTED_GATES, __version__
from .errors import InputError
from .manifest import keys, sha256, vector

MAX_ROI_BYTES = 1024 * 1024
MAX_REGIONS = 1000
MAX_INTERSECTION_CHECKS = 1_000_000
SUPPORT_ROLES = frozenset(("Support material", "Support material interface"))
# Only these exact Prusa-style labels can exclude a deposition as non-support.
NON_SUPPORT_ROLES = frozenset((
    "Perimeter", "External perimeter", "Overhang perimeter", "Internal infill",
    "Solid infill", "Top solid infill", "Bridge infill", "Internal bridge infill",
    "Gap fill", "Skirt/Brim", "Skirt", "Brim", "Ironing", "Wipe tower",
))


def finite(value, label):
    if not math.isfinite(value):
        raise InputError(f"{label}: arithmetic overflow/nonfinite number")
    return value


def json_float(token):
    return finite(float(token), "ROI JSON number")


def json_int(token):
    # Bound before int conversion as well as before reusing manifest.vector.
    json_float(token)
    return int(token)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"duplicate ROI JSON key: {key}")
        result[key] = value
    return result


def reject_constant(token):
    raise InputError(f"nonfinite ROI JSON constant: {token}")


def load_regions(path, gcode_sha256):
    source = Path(path)
    with source.open("rb") as stream:
        raw = stream.read(MAX_ROI_BYTES + 1)
    if len(raw) > MAX_ROI_BYTES:
        raise InputError("ROI JSON exceeds the 1 MiB limit")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                          parse_constant=reject_constant, parse_float=json_float,
                          parse_int=json_int)
    except (ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise InputError(f"invalid ROI JSON: {error}") from error
    keys(data, ("schema_version", "frame", "units", "gcode_sha256", "regions"), label="ROI")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise InputError("ROI schema_version must be integer 1")
    if data["frame"] != "gcode_machine_coordinates" or data["units"] != "mm":
        raise InputError("ROI requires explicit gcode_machine_coordinates and mm; assembly transforms are unverified")
    digest = data["gcode_sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise InputError("invalid ROI gcode_sha256")
    if digest != gcode_sha256:
        raise InputError("ROI G-code SHA256 mismatch")
    regions = data["regions"]
    if not isinstance(regions, list) or not 1 <= len(regions) <= MAX_REGIONS:
        raise InputError(f"ROI regions must contain 1 to {MAX_REGIONS} AABBs")
    identifiers, normalized = set(), []
    for region in regions:
        keys(region, ("id", "min_mm", "max_mm"), label="ROI region")
        identifier = region["id"]
        if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 200:
            raise InputError("ROI id must be a nonempty string of at most 200 characters")
        if identifier in identifiers:
            raise InputError(f"duplicate ROI id: {identifier}")
        identifiers.add(identifier)
        lower = vector(region["min_mm"], "ROI min_mm")
        upper = vector(region["max_mm"], "ROI max_mm")
        if not all(a < b for a, b in zip(lower, upper)):
            raise InputError("ROI min_mm must be strictly less than max_mm on every axis")
        normalized.append({"id": identifier, "min_mm": lower, "max_mm": upper})
    # Bind the exact bytes parsed; detect a changed input with the shared hash helper.
    digest = hashlib.sha256(raw).hexdigest()
    if sha256(source) != digest:
        raise InputError("ROI changed while being read")
    return normalized, digest


def near_roundoff(a, b):
    return abs(a - b) <= 8 * max(math.ulp(a), math.ulp(b))


def exact_clip_interval(start, end, region, width, height):
    """Resolve boundary ties using exact rational decimal representations.

    This adds no geometric tolerance: a small positive separation stays a miss.
    """
    enter, leave = Fraction(0), Fraction(1)
    radii = (Fraction(str(width)) / 2, Fraction(str(width)) / 2, Fraction(str(height)))
    for axis, radius in enumerate(radii):
        lower = Fraction(str(region["min_mm"][axis])) - radius
        upper = Fraction(str(region["max_mm"][axis])) + radius
        origin = Fraction(str(start[axis]))
        delta = Fraction(str(end[axis])) - origin
        if delta == 0:
            if origin < lower or origin > upper:
                return None
            continue
        a, b = (lower - origin) / delta, (upper - origin) / delta
        enter, leave = max(enter, min(a, b)), min(leave, max(a, b))
        if enter > leave:
            return None
    return [float(enter), float(leave)]


def clip_interval(start, end, region, width, height):
    """Closed slab clip against ROI expanded by (width/2, width/2, height).

    t is measured from the deposited path start to end, including tangency.
    This tests the line itself, not just overlap of its bounding box.
    """
    enter, leave = 0., 1.
    bounds = [(finite(region["min_mm"][axis] - radius, "expanded ROI min"),
               finite(region["max_mm"][axis] + radius, "expanded ROI max"))
              for axis, radius in enumerate((width / 2, width / 2, height))]
    for axis, (lower, upper) in enumerate(bounds):
        delta = finite(end[axis] - start[axis], "path direction")
        if delta == 0:
            if near_roundoff(start[axis], lower) or near_roundoff(start[axis], upper):
                return exact_clip_interval(start, end, region, width, height)
            if start[axis] < lower or start[axis] > upper:
                return None
            continue
        a = finite(finite(lower - start[axis], "clip offset") / delta, "clip parameter")
        b = finite(finite(upper - start[axis], "clip offset") / delta, "clip parameter")
        enter, leave = max(enter, min(a, b)), min(leave, max(a, b))
        if enter > leave:
            if near_roundoff(enter, leave):
                return exact_clip_interval(start, end, region, width, height)
            return None
    if near_roundoff(enter, leave):
        return exact_clip_interval(start, end, region, width, height)
    return [enter, leave]


def screen_support(summary, segments, stationary_events, regions):
    hits, gaps, eligible = [], [], []
    for kind, events in (("moving_extrusion", segments), ("stationary_prime", stationary_events)):
        for event in events:
            reasons = []
            role = event["role"]
            if role not in SUPPORT_ROLES | NON_SUPPORT_ROLES:
                reasons.append("unknown_role")
            if event["width_mm"] is None or event["height_mm"] is None:
                reasons.append("missing_dimensions")
            if kind == "stationary_prime":
                start = end = event["position_mm"]
                if any(value is None for value in start):
                    reasons.append("unknown_stationary_position")
            else:
                start, end = event["from_mm"], event["to_mm"]
                if start[2] != end[2]:
                    reasons.append("nonplanar_deposition")
            if reasons:
                gaps.append({"line": event["line"], "role": role, "kind": kind, "reasons": reasons})
            elif role in SUPPORT_ROLES:
                eligible.append((kind, event, start, end))
    if len(eligible) * len(regions) > MAX_INTERSECTION_CHECKS:
        raise InputError(f"support screen exceeds {MAX_INTERSECTION_CHECKS} intersection checks")
    for kind, event, start, end in eligible:
        for region in regions:
            interval = clip_interval(start, end, region, event["width_mm"], event["height_mm"])
            if interval is not None:
                hits.append({"line": event["line"], "role": event["role"], "kind": kind,
                             "roi_id": region["id"], "clip_interval": interval,
                             "from_mm": start, "to_mm": end,
                             "width_mm": event["width_mm"], "height_mm": event["height_mm"]})
    hits.sort(key=lambda hit: (hit["line"], hit["roi_id"]))
    gaps.sort(key=lambda gap: gap["line"])
    return {
        "schema_version": 1, "tool_version": __version__, "command": "screen-support",
        "frame": "gcode_machine_coordinates", "units": "mm",
        "proxy": "axis_aligned_envelope_proxy",
        "proxy_expansion": {"xy": "width_mm/2", "z": "height_mm", "boundary": "closed"},
        "regions": regions, "extrusion_segments": summary["extrusion_segments"],
        "stationary_extrusion_mm": summary["stationary_extrusion_mm"],
        "screened_support_events": len(eligible), "intersection_checks": len(eligible) * len(regions),
        "observed_hits": hits, "coverage_complete": not gaps, "coverage_gaps": gaps,
        "outcome": "candidate_found" if hits else ("no_candidate_observed" if not gaps else "unknown"),
        "support_removal": "not_implemented", "physical_validation": "not_performed",
        "printer_ready": False, "assembly_to_gcode_transform_verified": False,
        "unimplemented_gates": dict(UNIMPLEMENTED_GATES),
        "limits": [
            "This screens nominal paths with an axis-aligned envelope proxy, not actual bead geometry.",
            "No guarantee of sagging, support removal, post-removal function, bonding, or strength.",
            "Coverage concerns only the supported dialect, exact role labels, and supplied machine-frame ROIs.",
            "Unknown roles, missing dimensions, nonplanar deposition, and unlocated primes leave coverage incomplete.",
            "Known support primes use a point envelope; widths/heights are metadata, not measurements.",
            "Assembly-coordinate transforms are unverified and are not accepted.",
        ],
    }
