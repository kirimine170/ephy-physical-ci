"""Local PrusaSlicer adapter. Never uploads, connects to, or starts a printer."""
import copy
from contextlib import contextmanager
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .errors import BackendError, InputError
from .gcode import extract
from .manifest import sha256

MAX_PROFILE_BYTES = 1024 * 1024
MAX_MESH_BYTES = 64 * 1024 * 1024
MAX_GCODE_BYTES = 64 * 1024 * 1024
INPUT_LIMITS = {"profile": MAX_PROFILE_BYTES, "print_mesh": MAX_MESH_BYTES}


def inspect_profile(path):
    # Slicer INI post_process can execute programs. Network credentials are not needed.
    settings = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if "=" not in line:
            raise InputError("only a flat PrusaSlicer INI configuration is supported")
        key, value = (part.strip() for part in line.split("=", 1))
        if key in settings:
            raise InputError(f"duplicate profile setting: {key}")
        settings[key] = value
        if value and (key.lower() == "post_process" or key.lower().startswith(("printhost_", "print_host")) or
                      any(word in key.lower() for word in ("password", "api_key", "apikey", "token"))):
            raise InputError(f"profile contains disallowed executable/network/secret setting: {key}")
    if settings.get("gcode_comments") != "1" or settings.get("binary_gcode") != "0":
        raise InputError("profile must enable gcode_comments=1 and binary_gcode=0")
    return settings


def read_bounded(path, limit, label):
    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    if not raw or len(raw) > limit:
        raise InputError(f"{label} must contain 1 to {limit} bytes")
    return raw


def verify_input_snapshots(snapshots, digests):
    for key, snapshot in snapshots.items():
        if snapshot.is_symlink() or not snapshot.is_file():
            raise InputError(f"{key} snapshot is missing or is not a regular copied file")
        raw = read_bounded(snapshot, INPUT_LIMITS[key], f"{key} snapshot")
        if hashlib.sha256(raw).hexdigest() != digests[key]:
            raise InputError(f"{key} snapshot changed during slicing")


@contextmanager
def input_snapshots(manifest, paths, directory):
    """Bind copied input bytes, safety inspection and backend paths to one hash.

    This isolates ordinary edits of original files, not a same-UID adversary
    mutating and restoring the private snapshots between integrity checks.
    """
    snapshots, digests = {}, {}
    for key, limit in INPUT_LIMITS.items():
        expected = manifest.get("artifacts", {}).get(key, {}).get("sha256")
        if key not in paths or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise InputError(f"{key} requires a manifest-bound input SHA256")
        original = Path(paths[key])
        raw = read_bounded(original, limit, key)
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected:
            raise InputError(f"{key} SHA256 mismatch while creating slicer snapshot")
        parent = Path(directory) / "inputs" / key
        parent.mkdir(parents=True)
        # Preserve the basename used by slicer filename placeholders. Separate
        # directories avoid collisions between an INI and the mesh.
        snapshot = parent / original.name
        with snapshot.open("xb") as stream:
            stream.write(raw)
        snapshots[key], digests[key] = snapshot, actual
    verify_input_snapshots(snapshots, digests)
    inspect_profile(snapshots["profile"])
    verify_input_snapshots(snapshots, digests)
    yield snapshots, digests
    verify_input_snapshots(snapshots, digests)


def run_slicer(manifest, paths, manifest_sha256, executable, output_dir, timeout=120):
    if "slicing" not in manifest:
        raise InputError("manifest has no slicing specification")
    manifest = copy.deepcopy(manifest)
    paths = {key: Path(path) for key, path in paths.items()}
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "toolpath.analysis-only.gcode"
    reserved = [output / name for name in ("toolpath.analysis-only.gcode", "slicer.local.log", "summary.json", "segments.jsonl")]
    if any(target.exists() or target.is_symlink() for target in reserved):
        raise InputError("slice outputs already exist; use a fresh output directory")
    if any(target.resolve() == p.resolve() for target in reserved for p in paths.values()):
        raise InputError("output must not overwrite an input artifact")
    binary = shutil.which(executable)
    if not binary:
        raise BackendError("PrusaSlicer executable was not found")
    config = manifest["slicing"]
    # Inputs and generated data stay in a fresh private run directory. The
    # datadir is separate, so slicer settings cannot overwrite input snapshots.
    with tempfile.TemporaryDirectory(prefix=".slicer-run-", dir=output) as run_dir:
        run_root = Path(run_dir)
        config_dir = run_root / "config"
        config_dir.mkdir()
        temporary_gcode = run_root / "generated.gcode"
        with input_snapshots(manifest, paths, run_root) as (snapshots, input_digests):
            try:
                help_result = subprocess.run([binary, "--help"], capture_output=True, text=True, timeout=15)
            except (OSError, subprocess.TimeoutExpired) as error:
                raise BackendError("cannot query PrusaSlicer version") from error
            header = help_result.stdout + help_result.stderr
            match = re.search(r"PrusaSlicer[- ](\d+\.\d+\.\d+)([^\s]*)", header)
            if help_result.returncode or not match or match.group(1) != config["expected_version"] or (match.group(2) and not match.group(2).startswith("+")):
                raise BackendError("PrusaSlicer version does not match the pinned manifest version")
            verify_input_snapshots(snapshots, input_digests)
            args = [binary, "--datadir", str(config_dir), "--config-compatibility", "disable",
                    "--load", str(snapshots["profile"]), "--export-gcode", "--center",
                    ",".join(str(v) for v in config["center_mm"])]
            args += ["--no-support-material"] if config["support_mode"] == "none" else ["--support-material", "--support-material-auto"]
            args += ["--output", str(temporary_gcode), str(snapshots["print_mesh"])]
            try:
                result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
            except (OSError, subprocess.TimeoutExpired) as error:
                raise BackendError("PrusaSlicer failed to run or exceeded its timeout") from error
            # Local logs may contain paths; never publish them automatically.
            with (output / "slicer.local.log").open("x", encoding="utf-8") as stream:
                stream.write(result.stdout + result.stderr)
            verify_input_snapshots(snapshots, input_digests)
            if result.returncode or not temporary_gcode.is_file() or temporary_gcode.is_symlink():
                raise BackendError("PrusaSlicer failed; inspect the local log")
            raw_gcode = read_bounded(temporary_gcode, MAX_GCODE_BYTES, "G-code")
            summary, segments = extract(raw_gcode.decode("utf-8"))
        # The context verifies snapshots again after parsing. Build the report
        # before publishing any successful G-code artifact.
        summary.update({"command": "slice", "manifest_sha256": manifest_sha256,
                        "gcode_sha256": hashlib.sha256(raw_gcode).hexdigest(), "gcode_file": destination.name,
                        "slicer": {"name": "PrusaSlicer", "version": match.group(1), "build_suffix": match.group(2), "executable_sha256": sha256(binary)},
                        "input_sha256": {key: value["sha256"] for key,value in manifest["artifacts"].items()},
                        "consumed_input_sha256": input_digests,
                        "input_binding": "verified_private_snapshots",
                        "declared_assembly_to_print": manifest["assembly_to_print"],
                        "slicer_center_mm": config["center_mm"], "support_mode": config["support_mode"],
                        "assembly_to_print_geometry_verified": False, "printer_ready": False})
        validated_gcode = run_root / "validated.gcode"
        with validated_gcode.open("xb") as stream:
            stream.write(raw_gcode)
        # Same-filesystem hard-link publication is atomic and refuses a target
        # created after preflight; it never overwrites a concurrent output.
        os.link(validated_gcode, destination)
    return summary, segments
