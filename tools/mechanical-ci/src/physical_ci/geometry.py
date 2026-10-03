"""Independent checker: frozen STEP only, with no generator-code imports."""
import math
import platform

from . import UNIMPLEMENTED_GATES, __version__
from .errors import BackendError, InputError


def sampled_positions(waypoints, step, max_samples=10000):
    result = [tuple(waypoints[0])]
    for start, end in zip(waypoints, waypoints[1:]):
        distance = math.dist(start, end)
        required = distance / step
        if not math.isfinite(required) or required > max_samples:
            raise InputError(f"path exceeds the {max_samples}-sample limit")
        count = max(1, math.ceil(required))
        if len(result) + count > max_samples:
            raise InputError(f"path exceeds the {max_samples}-sample limit")
        result.extend(tuple(a+(b-a)*i/count for a,b in zip(start,end)) for i in range(1,count+1))
    return result


def check_path(manifest, paths, manifest_sha256):
    if "path_check" not in manifest:
        raise InputError("manifest has no path_check")
    check = manifest["path_check"]
    positions = sampled_positions(check["waypoints_mm"], check["max_step_mm"])
    try:
        import cadquery as cq
    except ImportError as error:
        raise BackendError("install the geometry extra to read frozen STEP files") from error
    shapes, records = {}, {}
    for key in ("fixed", "moving"):
        try:
            imported = cq.importers.importStep(str(paths[key])).vals()
        except Exception as error:
            raise BackendError(f"cannot import the {key} frozen STEP") from error
        if len(imported) != 1 or len(imported[0].Solids()) != 1 or not imported[0].isValid():
            raise InputError(f"{key} STEP must contain exactly one valid solid")
        shapes[key] = imported[0]
        records[key] = {"sha256": manifest["artifacts"][key]["sha256"], "valid_single_solid": True,
                        "volume_mm3": imported[0].Volume()}
    samples = []
    for index, position in enumerate(positions):
        volume = shapes["fixed"].intersect(shapes["moving"].translate(position)).Volume()
        if not math.isfinite(volume) or volume < -1e-9:
            raise BackendError("CAD kernel returned an invalid intersection volume")
        samples.append({"index": index, "translation_mm": list(position), "intersection_mm3": volume,
                        "colliding": volume > check["volume_tolerance_mm3"]})
    first = next((sample for sample in samples if sample["colliding"]), None)
    outcome = "collision_found" if first else "sampled_clear"
    expected = check.get("expected_outcome")
    return {"schema_version": 1, "tool_version": __version__, "command": "check-path",
            "manifest_sha256": manifest_sha256, "units": "mm", "frame": "assembly",
            "backend": {"name": "CadQuery", "version": cq.__version__, "python": platform.python_version()},
            "inputs": records, "outcome": outcome, "expected_outcome": expected,
            "regression_passed": outcome == expected if expected else None,
            "sample_count": len(samples), "first_collision": first, "samples": samples,
            "unimplemented_gates": dict(UNIMPLEMENTED_GATES),
            "limits": ["Discrete samples can miss collisions between poses.",
                       "Sampled-clear is not a continuous escape proof.",
                       "Blocked path is not a proof that every escape path is blocked.",
                       "Rigid intersection volume is not force, stress, or printability."]}
