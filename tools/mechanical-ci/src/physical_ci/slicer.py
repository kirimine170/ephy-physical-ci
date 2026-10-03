"""Local PrusaSlicer adapter. Never uploads, connects to, or starts a printer."""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .errors import BackendError, InputError
from .gcode import extract
from .manifest import sha256


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


def run_slicer(manifest, paths, manifest_sha256, executable, output_dir, timeout=120):
    if "slicing" not in manifest:
        raise InputError("manifest has no slicing specification")
    inspect_profile(paths["profile"])
    binary = shutil.which(executable)
    if not binary:
        raise BackendError("PrusaSlicer executable was not found")
    try:
        help_result = subprocess.run([binary, "--help"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BackendError("cannot query PrusaSlicer version") from error
    header = help_result.stdout + help_result.stderr
    match = re.search(r"PrusaSlicer[- ](\d+\.\d+\.\d+)([^\s]*)", header)
    config = manifest["slicing"]
    if help_result.returncode or not match or match.group(1) != config["expected_version"] or (match.group(2) and not match.group(2).startswith("+")):
        raise BackendError("PrusaSlicer version does not match the pinned manifest version")
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "toolpath.analysis-only.gcode"
    reserved = [output / name for name in ("toolpath.analysis-only.gcode", "slicer.local.log", "summary.json", "segments.jsonl")]
    if any(target.exists() or target.is_symlink() for target in reserved):
        raise InputError("slice outputs already exist; use a fresh output directory")
    if any(target.resolve() == p.resolve() for target in reserved for p in paths.values()):
        raise InputError("output must not overwrite an input artifact")
    # Fresh per-run config avoids user-global profiles and settings.
    with tempfile.TemporaryDirectory(prefix=".slicer-config-", dir=output) as config_dir:
        temporary_gcode = Path(config_dir) / "generated.gcode"
        args = [binary, "--datadir", config_dir, "--config-compatibility", "disable",
                "--load", str(paths["profile"]), "--export-gcode", "--center",
                ",".join(str(v) for v in config["center_mm"])]
        args += ["--no-support-material"] if config["support_mode"] == "none" else ["--support-material", "--support-material-auto"]
        args += ["--output", str(temporary_gcode), str(paths["print_mesh"])]
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise BackendError("PrusaSlicer failed to run or exceeded its timeout") from error
        # Local logs may contain paths; never publish them automatically.
        (output / "slicer.local.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode or not temporary_gcode.is_file():
            raise BackendError("PrusaSlicer failed; inspect the local log")
        if temporary_gcode.stat().st_size > 64 * 1024 * 1024:
            raise InputError("G-code exceeds this prototype's 64 MiB limit")
        summary, segments = extract(temporary_gcode.read_text(encoding="utf-8"))
        shutil.move(str(temporary_gcode), destination)
    summary.update({"command": "slice", "manifest_sha256": manifest_sha256,
                    "gcode_sha256": sha256(destination), "gcode_file": destination.name,
                    "slicer": {"name": "PrusaSlicer", "version": match.group(1), "build_suffix": match.group(2), "executable_sha256": sha256(binary)},
                    "input_sha256": {key: value["sha256"] for key,value in manifest["artifacts"].items()},
                    "declared_assembly_to_print": manifest["assembly_to_print"],
                    "slicer_center_mm": config["center_mm"], "support_mode": config["support_mode"],
                    "assembly_to_print_geometry_verified": False, "printer_ready": False})
    return summary, segments
