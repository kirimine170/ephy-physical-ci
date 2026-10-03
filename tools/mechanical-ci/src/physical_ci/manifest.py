"""Versioned, deliberately small manifest contract with hash-checked inputs."""
import hashlib
import json
import math
from pathlib import Path, PurePosixPath

from .errors import InputError


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def keys(value, required, optional=(), label="object"):
    if not isinstance(value, dict):
        raise InputError(f"{label} must be an object")
    missing, extra = set(required) - value.keys(), value.keys() - set(required) - set(optional)
    if missing or extra:
        raise InputError(f"{label}: missing={sorted(missing)}, unknown={sorted(extra)}")


def number(value, label, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InputError(f"{label} must be a finite number")
    if positive and value <= 0 or nonnegative and value < 0:
        raise InputError(f"{label} is out of range")
    return float(value)


def vector(value, label, size=3):
    if not isinstance(value, list) or len(value) != size:
        raise InputError(f"{label} needs {size} numbers")
    return [number(n, label) for n in value]


def rigid_matrix(value):
    if not isinstance(value, list) or len(value) != 4:
        raise InputError("assembly_to_print must be a 4x4 rigid matrix")
    rows = [vector(row, "assembly_to_print", 4) for row in value]
    if rows[3] != [0., 0., 0., 1.]:
        raise InputError("assembly_to_print last row must be [0,0,0,1]")
    for i in range(3):
        for j in range(3):
            dot = sum(rows[i][k] * rows[j][k] for k in range(3))
            if not math.isclose(dot, float(i == j), abs_tol=1e-8):
                raise InputError("assembly_to_print rotation must be orthonormal")
    a, b, c = [row[:3] for row in rows[:3]]
    determinant = a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0])
    if not math.isclose(determinant, 1., abs_tol=1e-8):
        raise InputError("assembly_to_print must not reflect or scale geometry")


def resolve_artifact(root, artifact):
    keys(artifact, ("path", "sha256", "frame"), label="artifact")
    name = artifact["path"]
    if not isinstance(name, str) or "\\" in name:
        raise InputError("artifact path must be a relative POSIX path")
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts:
        raise InputError("artifact path must stay inside the manifest directory")
    full = (root / name).resolve()
    if not full.is_relative_to(root) or not full.is_file():
        raise InputError(f"missing or out-of-root artifact: {name}")
    digest = artifact["sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise InputError(f"invalid SHA256: {name}")
    if sha256(full) != digest:
        raise InputError(f"SHA256 mismatch: {name}")
    if artifact["frame"] not in ("assembly", "print", "configuration"):
        raise InputError(f"unknown artifact frame: {name}")
    return full


def load_manifest(path):
    source = Path(path).resolve()
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise InputError(f"cannot read manifest: {error}") from error
    keys(data, ("schema_version", "name", "units", "assembly_to_print", "artifacts"),
         ("path_check", "slicing"), "manifest")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise InputError("supported schema_version is 1")
    if not isinstance(data["name"], str) or not data["name"].strip():
        raise InputError("name must be a nonempty string")
    if data["units"] != "mm":
        raise InputError("only explicit millimetre inputs are supported")
    rigid_matrix(data["assembly_to_print"])
    artifacts = data["artifacts"]
    keys(artifacts, (), ("fixed", "moving", "print_mesh", "profile"), "artifacts")
    resolved = {key: resolve_artifact(source.parent, value) for key, value in artifacts.items()}
    if not data.get("path_check") and not data.get("slicing"):
        raise InputError("manifest needs path_check or slicing")
    if "path_check" in data:
        check = data["path_check"]
        keys(check, ("kind", "frame", "waypoints_mm", "max_step_mm", "volume_tolerance_mm3", "expected_outcome"),
             label="path_check")
        if check["kind"] != "sampled_translation" or check["frame"] != "assembly":
            raise InputError("only sampled_translation in the assembly frame is supported")
        for key in ("fixed", "moving"):
            if key not in artifacts or artifacts[key]["frame"] != "assembly":
                raise InputError(f"{key} STEP must be in assembly coordinates")
            if resolved[key].suffix.lower() not in (".step", ".stp"):
                raise InputError(f"{key} must be a frozen STEP file")
        points = check["waypoints_mm"]
        if not isinstance(points, list) or not 2 <= len(points) <= 100:
            raise InputError("waypoints_mm must contain 2 to 100 translation vectors")
        for point in points:
            vector(point, "waypoint")
        number(check["max_step_mm"], "max_step_mm", positive=True)
        number(check["volume_tolerance_mm3"], "volume_tolerance_mm3", nonnegative=True)
        if check.get("expected_outcome") not in ("sampled_clear", "collision_found"):
            raise InputError("invalid expected_outcome")
    if "slicing" in data:
        config = data["slicing"]
        keys(config, ("engine", "expected_version", "center_mm", "support_mode"), label="slicing")
        if config["engine"] != "PrusaSlicer" or not isinstance(config["expected_version"], str):
            raise InputError("slicing requires PrusaSlicer and an expected_version string")
        vector(config["center_mm"], "center_mm", 2)
        if config["support_mode"] not in ("none", "auto"):
            raise InputError("support_mode must be none or auto")
        for key, frame, suffix in (("print_mesh", "print", ".stl"), ("profile", "configuration", ".ini")):
            if key not in artifacts or artifacts[key]["frame"] != frame or resolved[key].suffix.lower() != suffix:
                raise InputError(f"{key} requires a {suffix} artifact in frame {frame}")
    return data, resolved, sha256(source)
