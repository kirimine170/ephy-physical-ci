"""Bounded straight axial screen of a flat-end cylinder against frozen STEP.

This exact sweep for one motion model is independent of sampled check-path.
It does not certify a complete tool assembly, removal, or physical safety.
"""
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import platform
import tempfile

from . import __version__
from .errors import BackendError, InputError
from .manifest import keys, number, sha256, vector

MAX_SPEC_BYTES = 64 * 1024
MAX_STEP_BYTES = 64 * 1024 * 1024
AXIS_NORM_EPSILON = 1e-12


def finite(value, label):
    if not math.isfinite(value):
        raise InputError(f"{label} arithmetic overflow/nonfinite value")
    return value


def json_float(token):
    value = finite(float(token), "tool JSON number")
    coefficient = token.lower().split("e", 1)[0]
    if value == 0 and any(digit in "123456789" for digit in coefficient):
        raise InputError("tool JSON number underflows to zero")
    return value


def json_int(token):
    json_float(token)  # Reject overflow before integer conversion/vector checks.
    return int(token)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"duplicate tool JSON key: {key}")
        result[key] = value
    return result


def reject_constant(token):
    raise InputError(f"nonfinite tool JSON constant: {token}")


def load_tool_spec(path):
    source = Path(path).resolve()
    with source.open("rb") as stream:
        raw = stream.read(MAX_SPEC_BYTES + 1)
    if len(raw) > MAX_SPEC_BYTES:
        raise InputError("tool specification exceeds the 64 KiB limit")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                          parse_float=json_float, parse_int=json_int,
                          parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise InputError(f"invalid tool specification JSON: {error}") from error
    keys(data, ("schema_version", "units", "frame", "obstacle", "tool",
                "numeric_epsilon_mm", "numeric_epsilon_mm3"), label="tool specification")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise InputError("tool schema_version must be integer 1")
    if data["units"] != "mm" or data["frame"] != "assembly":
        raise InputError("tool specification requires explicit mm and assembly coordinates")
    obstacle = data["obstacle"]
    keys(obstacle, ("path", "sha256", "frame"), label="obstacle")
    name = obstacle["path"]
    if not isinstance(name, str) or not name or "\\" in name:
        raise InputError("obstacle path must be a relative POSIX STEP path")
    relative = PurePosixPath(name)
    # Reject Windows drive/stream syntax as well as POSIX absolute paths.
    if relative.is_absolute() or ".." in relative.parts or ":" in name:
        raise InputError("obstacle path must stay inside the specification directory")
    step = (source.parent / name).resolve()
    if not step.is_relative_to(source.parent) or not step.is_file():
        raise InputError("missing or out-of-root obstacle STEP")
    if step.suffix.lower() not in (".step", ".stp") or obstacle["frame"] != "assembly":
        raise InputError("obstacle requires a frozen STEP in assembly coordinates")
    digest = obstacle["sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise InputError("invalid obstacle SHA256")
    tool = data["tool"]
    keys(tool, ("kind", "radius_mm", "length_mm", "tip_mm", "axis", "travel_mm"), label="tool")
    if tool["kind"] != "flat_end_cylinder":
        raise InputError("only flat_end_cylinder tools are supported")
    radius = number(tool["radius_mm"], "radius_mm", positive=True)
    length = number(tool["length_mm"], "length_mm", positive=True)
    travel = number(tool["travel_mm"], "travel_mm", nonnegative=True)
    tip, declared_axis = vector(tool["tip_mm"], "tip_mm"), vector(tool["axis"], "axis")
    norm = math.hypot(*declared_axis)
    if not math.isclose(norm, 1., rel_tol=0., abs_tol=AXIS_NORM_EPSILON):
        raise InputError("axis must be a unit vector (norm within 1e-12 of 1)")
    axis = [value / norm for value in declared_axis]
    swept_length = finite(length + travel, "swept length")
    base = [finite(p - length * d, "cylinder base") for p, d in zip(tip, axis)]
    end = [finite(p + travel * d, "final tip") for p, d in zip(tip, axis)]
    if finite(math.dist(base, end), "sweep extent") == 0 or travel > 0 and swept_length == length:
        raise InputError("sweep extent/travel is below coordinate or length resolution")
    expected_volume = finite(math.pi * radius * radius * swept_length, "swept volume")
    if expected_volume <= 0:
        raise InputError("swept volume underflows to zero")
    distance_epsilon = number(data["numeric_epsilon_mm"], "numeric_epsilon_mm", positive=True)
    volume_epsilon = number(data["numeric_epsilon_mm3"], "numeric_epsilon_mm3", positive=True)
    normalized = {
        "radius_mm": radius, "length_mm": length, "travel_mm": travel,
        "tip_mm": tip, "declared_axis": declared_axis, "axis": axis,
        "sweep_from_mm": base, "sweep_to_mm": end, "sweep_length_mm": swept_length,
        "expected_sweep_volume_mm3": expected_volume,
        "numeric_epsilon_mm": distance_epsilon, "numeric_epsilon_mm3": volume_epsilon,
        "obstacle_sha256": digest,
    }
    return normalized, step, hashlib.sha256(raw).hexdigest()


@contextmanager
def step_snapshot(source, expected_sha256):
    """Hash and import the same bounded bytes; never import the live source."""
    with Path(source).open("rb") as stream:
        raw = stream.read(MAX_STEP_BYTES + 1)
    if not raw or len(raw) > MAX_STEP_BYTES:
        raise InputError("obstacle STEP must contain 1 byte to 64 MiB")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha256:
        raise InputError("obstacle STEP SHA256 mismatch")
    with tempfile.TemporaryDirectory(prefix=".physical-ci-step-") as directory:
        snapshot = Path(directory) / "obstacle.step"
        with snapshot.open("xb") as stream:
            stream.write(raw)
        if sha256(snapshot) != digest:
            raise InputError("STEP snapshot bytes differ from the read input")
        yield snapshot, digest
        if not snapshot.is_file() or sha256(snapshot) != digest:
            raise InputError("STEP snapshot changed during kernel analysis")


def valid_single_solid(shape):
    solids = shape.Solids()
    if len(solids) != 1 or not shape.isValid() or not solids[0].isValid():
        raise InputError("obstacle STEP must contain exactly one valid solid")
    solid = solids[0]
    # Allow a single-solid STEP wrapper, but never discard stray faces/edges.
    for topology in ("Faces", "Edges", "Vertices"):
        if len(getattr(shape, topology)()) != len(getattr(solid, topology)()):
            raise InputError("obstacle STEP contains geometry outside its single solid")
    volume = solid.Volume()
    bounds = solid.BoundingBox()
    coordinates = [getattr(bounds, axis + side) for axis in "xyz" for side in ("min", "max")]
    if not math.isfinite(volume) or volume <= 0 or not all(math.isfinite(v) for v in coordinates):
        raise InputError("obstacle STEP has nonfinite/degenerate solid geometry")
    return solid, volume


def classify(volume, distance, distance_epsilon, volume_epsilon):
    if volume is None or distance is None:
        return "indeterminate", "invalid_kernel_metrics"
    if volume < 0 or distance < 0 or not math.isfinite(volume) or not math.isfinite(distance):
        return "indeterminate", "invalid_kernel_metrics"
    if volume > 0 and distance > distance_epsilon:
        return "indeterminate", "kernel_volume_distance_contradiction"
    if volume > volume_epsilon:
        return "interference", "volume_overlap"
    if volume > 0:
        return "indeterminate", "micro_overlap"
    if distance <= distance_epsilon:
        return "indeterminate", "contact_or_numeric_gap"
    return "model_clear", "zero_overlap_and_positive_gap"


def measure(obstacle, sweep, distance_epsilon, volume_epsilon):
    volume = distance = None
    reasons = []
    try:
        common = obstacle.intersect(sweep)
        measured = common.Volume()
        if not isinstance(measured, bool) and isinstance(measured, (int, float)) and math.isfinite(measured):
            volume = float(measured)
        if volume is not None and volume > 0 and not common.isValid():
            reasons.append("invalid_intersection_shape")
    except Exception:
        reasons.append("intersection_kernel_failure")
    try:
        measured = obstacle.distance(sweep)
        if not isinstance(measured, bool) and isinstance(measured, (int, float)) and math.isfinite(measured):
            distance = float(measured)
    except Exception:
        reasons.append("distance_kernel_failure")
    outcome, reason = classify(volume, distance, distance_epsilon, volume_epsilon)
    if reasons:
        outcome = "indeterminate"
    return volume, distance, outcome, reasons or [reason]


def construct_sweep(cq, spec):
    volume = None
    try:
        sweep = cq.Solid.makeCylinder(spec["radius_mm"], spec["sweep_length_mm"],
                                      cq.Vector(*spec["sweep_from_mm"]), cq.Vector(*spec["axis"]))
        measured = sweep.Volume()
        if not isinstance(measured, bool) and isinstance(measured, (int, float)) and math.isfinite(measured):
            volume = float(measured)
        if not sweep.isValid() or len(sweep.Solids()) != 1 or volume is None or volume <= 0:
            return None, volume, "invalid_swept_cylinder"
        # This analytic identity is independent of the user's overlap threshold.
        if not math.isclose(volume, spec["expected_sweep_volume_mm3"], rel_tol=1e-8, abs_tol=0.):
            return None, volume, "kernel_sweep_volume_contradiction"
        return sweep, volume, None
    except Exception:
        return None, volume, "sweep_kernel_failure"


def screen_tool(spec, source, spec_sha256):
    with step_snapshot(source, spec["obstacle_sha256"]) as (snapshot, digest):
        try:
            import cadquery as cq
        except ImportError as error:
            raise BackendError("existing geometry extra (CadQuery/OCCT) is required for screen-tool") from error
        try:
            imported = cq.importers.importStep(str(snapshot)).vals()
            if len(imported) != 1:
                raise InputError("obstacle STEP must contain exactly one valid solid")
            obstacle, obstacle_volume = valid_single_solid(imported[0])
        except InputError:
            raise
        except Exception as error:
            raise InputError("cannot import a valid single-solid frozen obstacle STEP") from error
        sweep, sweep_volume, sweep_error = construct_sweep(cq, spec)
        if sweep_error:
            volume = distance = None
            outcome, reasons = "indeterminate", [sweep_error]
        else:
            volume, distance, outcome, reasons = measure(obstacle, sweep, spec["numeric_epsilon_mm"], spec["numeric_epsilon_mm3"])
        result = {
            "schema_version": 1, "tool_version": __version__, "command": "screen-tool",
            "manifest_sha256": spec_sha256, "frame": "assembly", "units": "mm",
            "backend": {"name": "CadQuery/OCCT", "version": cq.__version__, "python": platform.python_version()},
            "input": {"step_sha256": digest, "snapshot_hash_verified": True,
                      "valid_single_solid": True, "volume_mm3": obstacle_volume},
            "tool": {key: spec[key] for key in ("radius_mm", "length_mm", "tip_mm", "declared_axis", "axis", "travel_mm")},
            "sweep": {"kind": "axial_flat_end_cylinder", "from_mm": spec["sweep_from_mm"],
                      "to_mm": spec["sweep_to_mm"], "length_mm": spec["sweep_length_mm"],
                      "volume_mm3": sweep_volume, "geometry_verified": sweep_error is None},
            "numeric_epsilon_mm": spec["numeric_epsilon_mm"], "numeric_epsilon_mm3": spec["numeric_epsilon_mm3"],
            "intersection_mm3": volume, "minimum_distance_mm": distance,
            "outcome": outcome, "reasons": reasons, "model_clear": outcome == "model_clear",
            "continuous_for_this_motion_model": sweep_error is None,
            "full_tool_assembly_verified": False, "grip_access_verified": False,
            "support_breakage": "not_implemented", "support_removal": "not_implemented",
            "rotation_or_lateral_motion": "not_implemented", "path_search": "not_implemented",
            "physical_validation": "not_performed", "physical_safety_verified": False, "printer_ready": False,
            "limits": [
                "Only a nominal flat-end cylinder translating along its fixed unit axis is modeled.",
                "The swept cylinder covers the whole specified translation, including initial and final tool poses.",
                "Numeric epsilons are kernel decision thresholds, not manufacturing clearance tolerances.",
                "Model-clear is not a complete-tool, holder, gripping, support-fracture, or removal-access guarantee.",
                "No guarantee of physical safety, forces, material behavior, or printer readiness.",
                "No rotation, lateral motion, or path search is evaluated; sampled check-path is a separate stage.",
                "Reported input hash binds the private STEP snapshot, not subsequent edits of the live source.",
            ],
        }
    # Exiting the context verifies the imported snapshot's bytes before return.
    return result
