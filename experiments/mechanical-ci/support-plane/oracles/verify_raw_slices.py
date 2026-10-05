"""Independent Decimal modal scanner for these four pinned linear G-code files."""
from pathlib import Path
from decimal import Decimal as D
import hashlib
import json
import re
import sys

root = Path(sys.argv[1]).resolve()
manifest_raw = (root / "manifest.json").read_bytes()
manifest = json.loads(manifest_raw)
for name, digest in manifest.items():
    assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, name


def turn(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def on(a, b, p):
    return turn(a, b, p) == 0 and all(min(a[i], b[i]) <= p[i] <= max(a[i], b[i]) for i in (0, 1))


def crosses(a, b):
    if any(85 <= p[0] <= 95 and 84 <= p[1] <= 96 for p in (a, b)):
        return True
    corners = [(85, 84), (95, 84), (95, 96), (85, 96)]
    for i, c in enumerate(corners):
        d = corners[(i+1) % 4]
        values = [turn(a, b, c), turn(a, b, d), turn(c, d, a), turn(c, d, b)]
        if (values[0]*values[1] < 0 and values[2]*values[3] < 0) or on(a, b, c) or on(a, b, d) or on(c, d, a) or on(c, d, b):
            return True
    return False


def parse(text):
    xyz, relative_e, previous_e, debt = [None]*3, False, D(0), D(0)
    role, height, events = "", None, []
    for line_number, line in enumerate(text.splitlines(), 1):
        if line.startswith(";TYPE:"):
            role = line.split(":", 1)[1].strip()
        if line.startswith(";HEIGHT:"):
            height = D(line.split(":", 1)[1])
        parts = line.split(";", 1)[0].split()
        if not parts:
            continue
        command = parts[0]
        parameters = {word[0]: D(word[1:]) for word in parts[1:]
                      if re.fullmatch(r"[XYZE][-+]?(?:\d+(?:\.\d*)?|\.\d+)", word)}
        assert command not in ("G20", "G91", "G2", "G3"), (line_number, command)
        if command == "M83":
            relative_e = True
        if command == "M82":
            relative_e = False
        if command == "G92":
            assert not any(key in parameters for key in "XYZ")
            previous_e = parameters.get("E", previous_e)
        if command not in ("G0", "G1"):
            continue
        start = xyz[:]
        for i, key in enumerate("XYZ"):
            xyz[i] = parameters.get(key, xyz[i])
        delta = (parameters["E"] if relative_e else parameters["E"]-previous_e) if "E" in parameters else D(0)
        if "E" in parameters:
            previous_e = previous_e+parameters["E"] if relative_e else parameters["E"]
        if delta < 0:
            debt -= delta
        deposited = max(D(0), delta-debt)
        if delta > 0:
            debt = max(D(0), debt-delta)
        if deposited <= 0 or None in start or None in xyz or start == xyz:
            continue
        assert start[2] == xyz[2], line_number
        if crosses(start, xyz):
            events.append((line_number, role, xyz[2], height))
    return events


observations = []
model_roles = {"Perimeter", "External perimeter", "Overhang perimeter", "Internal infill",
               "Solid infill", "Top solid infill", "Ironing", "Bridge infill", "Gap fill"}
for case in sorted(root.glob("contact-*")):
    raw = (case / "toolpath.analysis-only.gcode").read_bytes()
    text = raw.decode()
    events = parse(text)
    support = [event for event in events if event[1] in ("Support material", "Support material interface")]
    top = max(event[2] for event in support)
    witnesses = {event[0] for event in support if event[2] == top}
    model = [event for event in events if event[1] in model_roles and event[2] >= 12]
    model_z = min(event[2] for event in model)
    model_witnesses = [event for event in model if event[2] == model_z]
    report = json.loads((case / "plane-report.json").read_text())
    assert D(str(report["known_selected_top_z_mm"])) == top
    assert witnesses == {event["line"] for event in report["top_witnesses"]}
    assert model_z == D(str(report["known_first_model_plane_at_or_above_nominal_z_mm"]))
    assert {event[0] for event in model_witnesses} == {event["line"] for event in report["known_first_model_plane_witnesses"]}
    settings = dict(re.findall(r"^; ([a-z_]+) = (.*)$", text, re.M))
    gap = D(case.name.removeprefix("contact-"))
    for key, value in {"z_offset": "0", "thick_bridges": "1", "bridge_flow_ratio": "1",
                       "nozzle_diameter": "0.4", "layer_height": "0.2", "first_layer_height": "0.2",
                       "support_material_synchronize_layers": "0", "support_material_style": "grid"}.items():
        assert settings[key] == value, (case.name, key)
    assert D(settings["support_material_contact_distance"]) == gap
    observations.append({"case": case.name, "gcode_sha256": hashlib.sha256(raw).hexdigest(),
                         "selected_top_z_mm": str(top), "nominal_plane_distance_mm": str(12-top),
                         "top_witness_lines": sorted(witnesses), "model_z_mm": str(model_z),
                         "model_roles": sorted({event[1] for event in model_witnesses}),
                         "model_height_metadata_mm": sorted({str(event[3]) for event in model_witnesses})})

profiles = {path.name: dict(line.split(" = ", 1) for line in path.read_text().splitlines() if " = " in line)
            for path in (root / "inputs").glob("*.ini")}
all_keys = set().union(*(set(profile) for profile in profiles.values()))
changed = [key for key in all_keys if len({profile.get(key) for profile in profiles.values()}) > 1]
assert changed == ["support_material_contact_distance"]
preregistered = (root / "preregistered.json").read_bytes()
assert json.loads(preregistered) == json.loads((Path(__file__).parent / "slicer-study-plan.json").read_text())
assert (root / "manifest.json").read_bytes() == manifest_raw
for name, digest in manifest.items():
    assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
print(json.dumps({"all_4_raw_audits_passed": True, "manifest_entries_verified": len(manifest),
                  "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
                  "preregistered_sha256": hashlib.sha256(preregistered).hexdigest(),
                  "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "only_changed_profile_key": changed, "observations": observations,
                  "scope": "Command-plane observations only; not physical air gap or force validation."}, indent=2))
