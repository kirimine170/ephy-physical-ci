"""Fault injection for reproducer gates; the placeholder binary is never run."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from unittest.mock import patch

source, evidence, output = map(lambda value: Path(value).resolve(), sys.argv[1:4])
fault = sys.argv[4]
sys.path.insert(0, str(source.parent))
spec = importlib.util.spec_from_file_location("reviewed_reproducer", source)
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)
binary = output.parent / (output.name + ".placeholder")
binary.write_bytes(b"Non-executable test placeholder; no software invocation")
original_sha = study.sha


def hash_stub(path):
    return study.SLICER_SHA256 if Path(path) == binary else original_sha(path)


def slice_stub(manifest, paths, digest, executable, destination):
    destination = Path(destination)
    destination.mkdir()
    name = destination.name
    raw = (evidence / name / "toolpath.analysis-only.gcode").read_bytes()
    if fault == "support_plane" and name == "contact-0.2":
        raw = re.sub(rb"(?m)^(G[01] .*?)Z11\.6(?=\s|$)", rb"\g<1>Z11.65", raw)
    if fault == "zero_model_role" and name == "contact-0":
        raw = raw.replace(b";TYPE:Solid infill", b";TYPE:Top solid infill")
    (destination / "toolpath.analysis-only.gcode").write_bytes(raw)
    summary = json.loads((evidence / name / "slice-summary.json").read_text())
    summary["gcode_sha256"] = hashlib.sha256(raw).hexdigest()
    return summary, []


with patch.object(study, "sha", side_effect=hash_stub), \
     patch.object(study.subprocess, "run", return_value=SimpleNamespace(stdout="PrusaSlicer-2.9.2+TEST\n", stderr="")), \
     patch.object(study, "run_slicer", side_effect=slice_stub):
    # Deliberately uncaught: this must terminate the process unsuccessfully.
    study.reproduce(binary, output)
