"""Generate only original synthetic bore fixtures and check analytic oracles."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import platform

from screen import ROOT, screen

BASE_COMMIT = "afafbf4983bc922fff40e8d8944269e5f0a1676f"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def specification(step, travel, tip=None, axis=None):
    return {"schema_version": 1, "units": "mm", "frame": "assembly",
            "obstacle": {"path": step.name, "sha256": sha(step), "frame": "assembly"},
            "motion": {"tip_mm": tip or [0, 0, -1], "axis": axis or [0, 0, 1], "travel_mm": travel},
            "components": [{"id": "tip", "backset_mm": 0, "length_mm": 2, "radius_mm": 1.5},
                           {"id": "handle", "backset_mm": 2, "length_mm": 4, "radius_mm": 3}],
            "numeric_epsilon_mm": 1e-7, "numeric_epsilon_mm3": 1e-9}


def build_bore(path, transform=False):
    import cadquery as cq
    shape = cq.Workplane("XY").box(20, 20, 1, centered=(True, True, False)).cut(
        cq.Workplane("XY").circle(2.5).extrude(1)).val()
    if transform:
        shape = shape.rotate((0, 0, 0), (0, 1, 0), 90).translate((11, -7, 5))
    cq.exporters.export(shape, str(path))


def expected(travel):
    # Preregistered geometry: slab z=[0,1], bore R=2.5; tip r=1.5,
    # backset=0,L=2; handle r=3, backset=2,L=4, common initial tip z=-1.
    # These are closed-form spatial relations, not product clipping results.
    if travel == 2.5:
        return {"outcome": "model_clear", "tip_distance": 1., "handle_distance": .5,
                "tip_volume": 0., "handle_volume": 0., "coverage_complete": True}
    if travel == 3:
        return {"outcome": "indeterminate", "tip_distance": 1., "handle_distance": 0.,
                "tip_volume": 0., "handle_volume": 0., "coverage_complete": False}
    if travel == 4:
        return {"outcome": "interference", "tip_distance": 1., "handle_distance": 0.,
                "tip_volume": 0., "handle_volume": 2.75 * math.pi, "coverage_complete": True}
    raise ValueError("unknown fixed oracle case")


def audit(report, oracle):
    checks = {"outcome": report["outcome"] == oracle["outcome"],
              "coverage": report["coverage_complete"] == oracle["coverage_complete"],
              "tip_model_clear": report["components"][0]["outcome"] == "model_clear",
              "union_volume_not_summed": report["union_intersection_volume_mm3"] is None,
              "same_obstacle_bytes": all(c["input"]["step_sha256"] == report["step_sha256"]
                                         for c in report["components"])}
    for component in report["components"]:
        name = component["component"]["id"]
        for field, suffix in (("intersection_mm3", "volume"), ("minimum_distance_mm", "distance")):
            observed = component[field]
            checks[f"{name}_{suffix}"] = (observed is not None and math.isclose(
                observed, oracle[f"{name}_{suffix}"], rel_tol=1e-8, abs_tol=1e-8))
    return checks


def reproduce(output):
    import cadquery as cq
    import OCP
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    # The expected outcomes are written BEFORE any generated geometry is measured.
    plan = {"fixture": "20x20x1 slab, through bore radius 2.5 mm",
            "coordinate_frame": "assembly, mm",
            "cases": [{"id": f"{pose}-{travel}", "travel_mm": travel,
                       "pose": pose, "expected": expected(travel)}
                      for pose in ("original", "rigid_transform") for travel in (2.5, 3, 4)],
            "rigid_transform": "rotate +90 degrees around Y, then translate (11,-7,5) mm",
            "oracle": "tip gap 1 mm; handle end z=travel-3; annular overlap 2.75*pi at travel4"}
    write(output / "preregistered.json", plan)
    rows = []
    for pose in ("original", "rigid_transform"):
        step = output / f"{pose}.step"
        transformed = pose == "rigid_transform"
        build_bore(step, transformed)
        for travel in (2.5, 3, 4):
            name = f"{pose}-{travel}"
            data = specification(step, travel, [10, -7, 5] if transformed else None,
                                 [1, 0, 0] if transformed else None)
            spec_path = output / f"{name}.json"
            write(spec_path, data)
            report = screen(spec_path)
            report_path = output / f"{name}.report.json"
            write(report_path, report)
            checks = audit(report, expected(travel))
            rows.append({"id": name, "outcome": report["outcome"], "checks": checks,
                         "passed": all(checks.values()), "report_sha256": sha(report_path)})
    result = {"base_commit": BASE_COMMIT, "python": platform.python_version(),
              "cadquery": cq.__version__, "OCP": OCP.__version__, "cases": rows,
              "passed": all(row["passed"] for row in rows),
              "source_sha256": {str(p.relative_to(ROOT)): sha(p) for p in (
                  Path(__file__), Path(__file__).with_name("screen.py"),
                  ROOT / "tools/mechanical-ci/src/physical_ci/tool.py")},
              "physical_validation": "not_performed"}
    write(output / "summary.json", result)
    write(output / "manifest.json", {p.name: sha(p) for p in sorted(output.iterdir()) if p.is_file()})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = reproduce(args.output)
    print(json.dumps({"passed": result["passed"], "cases": len(result["cases"])}))
    raise SystemExit(0 if result["passed"] else 1)
