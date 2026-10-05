"""Replay predeclared original fixtures against an independently supplied audit."""
import hashlib
import importlib.util
import json
import random
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
source = Path(sys.argv[1]).resolve()
before = source.read_bytes()
spec = importlib.util.spec_from_file_location("reviewed_plane_audit", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
plan_bytes = (root / "preregistered-oracles.json").read_bytes()
plan = json.loads(plan_bytes)
results = []
for name, case in plan["cases"].items():
    raw = (root / case["gcode_file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == case["sha256"]
    window = dict(plan["window"], schema_version=1, gcode_sha256=case["sha256"])
    report = module.audit_bytes(raw, json.dumps(window).encode())
    for key in ("known_selected_top_z_mm", "nominal_plane_minus_top_mm", "coverage_complete"):
        observed, expected = report[key], case["expected"][key]
        assert observed == expected or (
            type(observed) is float and type(expected) is float and abs(observed - expected) < 1e-12
        ), (name, key, observed, expected)
    results.append({"case": name, "gcode_sha256": case["sha256"],
                    "outcome": report["outcome"],
                    "known_selected_top_z_mm": report["known_selected_top_z_mm"],
                    "nominal_plane_minus_top_mm": report["nominal_plane_minus_top_mm"],
                    "coverage_complete": report["coverage_complete"]})
def orientation(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def on_segment(a, b, p):
    return orientation(a, b, p) == 0 and all(min(a[i], b[i]) <= p[i] <= max(a[i], b[i]) for i in (0, 1))


def edges_intersect(a, b, c, d):
    o1, o2 = orientation(a, b, c), orientation(a, b, d)
    o3, o4 = orientation(c, d, a), orientation(c, d, b)
    return (o1 * o2 < 0 and o3 * o4 < 0) or any((
        on_segment(a, b, c), on_segment(a, b, d), on_segment(c, d, a), on_segment(c, d, b)))


# Independent integer orientation/edge oracle, rather than the audit's slab clipping.
random_source = random.Random(1729)
corners = [(0, 0), (10, 0), (10, 10), (0, 10)]
for _ in range(2000):
    a = [random_source.randint(-20, 20), random_source.randint(-20, 20), 5]
    b = [random_source.randint(-20, 20), random_source.randint(-20, 20), 5]
    expected = any(all(0 <= q[j] <= 10 for j in (0, 1)) for q in (a, b)) or any(
        edges_intersect(a, b, corners[j], corners[(j + 1) % 4]) for j in range(4))
    assert (module.xy_intersection(a, b, [0, 0], [10, 10]) is not None) == expected

assert source.read_bytes() == before
print(json.dumps({"reviewed_audit_sha256": hashlib.sha256(before).hexdigest(),
                  "preregistered_oracles_sha256": hashlib.sha256(plan_bytes).hexdigest(),
                  "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "all_7_fixtures_passed": True, "integer_segment_oracles_passed": 2000,
                  "random_seed": 1729, "results": results}, indent=2))
