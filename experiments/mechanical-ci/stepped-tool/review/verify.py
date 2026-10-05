"""Independent local controls; never edits the implementation under review."""
import hashlib
import importlib.util
import itertools
import json
import math
from pathlib import Path
import sys
import tempfile

import cadquery as cq
import OCP

source = Path(sys.argv[1]).resolve()
source_bytes = source.read_bytes()
source_hash = hashlib.sha256(source_bytes).hexdigest()
assert source_hash == "790a8bf318f6a3c177a9448c868a3753e37034a552d7150c40ed69f0abcb0e05"
loader = importlib.util.spec_from_file_location("assembly_screen", source)
module = importlib.util.module_from_spec(loader)
loader.loader.exec_module(module)
results = []
component = {"id": "handle", "backset_mm": 3, "length_mm": 2, "radius_mm": 2}
for sign in (-1, 1):
    for axis in ([1, 0, 0], [.6, .8, 0]):
        motion = {"tip_mm": [sign * 1e16, sign * 1e16, 0], "axis": axis, "travel_mm": 2}
        try:
            module.component_tip(motion, component, 1e-7)
        except module.InputError as error:
            results.append({"kind": "rounded_backset_rejected", "motion": motion, "reason": str(error)})
        else:
            raise AssertionError("accepted unrepresentable backset")

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    step, specification = root / "shape.step", root / "tool.json"
    slab = cq.Solid.makeBox(20, 20, 1, cq.Vector(-10, -10, 0)).cut(
        cq.Solid.makeCylinder(2.5, 3, cq.Vector(0, 0, -1)))
    theta = math.radians(37)
    axis = [math.sin(theta), 0, math.cos(theta)]
    tip = [8 - axis[0], -3, 5 - axis[2]]
    cq.exporters.export(slab.rotate((0, 0, 0), (0, 1, 0), 37).translate((8, -3, 5)), str(step))
    for travel, expected in ((2.5, "model_clear"), (3, "indeterminate"), (4, "interference")):
        data = {"schema_version": 1, "units": "mm", "frame": "assembly",
                "obstacle": {"path": step.name, "sha256": hashlib.sha256(step.read_bytes()).hexdigest(), "frame": "assembly"},
                "motion": {"tip_mm": tip, "axis": axis, "travel_mm": travel},
                "components": [{"id": "front", "backset_mm": 0, "length_mm": 2, "radius_mm": 1.5},
                               {"id": "rear", "backset_mm": 2, "length_mm": 4, "radius_mm": 3}],
                "numeric_epsilon_mm": 1e-7, "numeric_epsilon_mm3": 1e-9}
        for reverse in (False, True):
            if reverse:
                data["components"].reverse()
            specification.write_text(json.dumps(data))
            report = module.screen(specification)
            assert report["outcome"] == expected
            components = {item["component"]["id"]: item for item in report["components"]}
            assert components["front"]["outcome"] == "model_clear"
            expected_volume = 2.75 * math.pi if travel == 4 else 0
            assert math.isclose(components["rear"]["intersection_mm3"], expected_volume, abs_tol=1e-8)
            if travel == 2.5:
                assert math.isclose(report["minimum_distance_mm"], .5, abs_tol=1e-8)
            results.append({"kind": "rotated_translated_bore", "rotation_Y_deg": 37,
                            "translation_mm": [8, -3, 5], "travel_mm": travel,
                            "component_order_reversed": reverse, "expected": expected,
                            "outcome": report["outcome"], "minimum_distance_mm": report["minimum_distance_mm"],
                            "rear_overlap_mm3": components["rear"]["intersection_mm3"],
                            "rear_overlap_oracle_mm3": expected_volume})

for a, b in itertools.product(("model_clear", "interference", "indeterminate"), repeat=2):
    rows = [{"outcome": value, "intersection_mm3": 1 if value == "interference" else 0,
             "minimum_distance_mm": .5 if value == "model_clear" else 0,
             "component": {"id": str(index)}} for index, value in enumerate((a, b))]
    report = module.aggregate(rows)
    expected = "interference" if "interference" in (a, b) else "model_clear" if a == b == "model_clear" else "indeterminate"
    assert report["outcome"] == expected
    results.append({"kind": "aggregation_mock", "inputs": [a, b], "outcome": report["outcome"]})

assert source.read_bytes() == source_bytes
print(json.dumps({"reviewed_screen_sha256": source_hash,
                  "review_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "cadquery": cq.__version__, "OCP": OCP.__version__,
                  "all_19_controls_passed": True, "controls": results,
                  "limits": "Synthetic nominal geometry and aggregation only; no physical force/removal validation."}, indent=2))
