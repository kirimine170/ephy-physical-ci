"""Create original synthetic regression geometry; not a usable snap-fit design.

The checker never imports this generator. It reads only frozen exported STEP.
"""
import hashlib
import json
import re
from pathlib import Path

import cadquery as cq

ROOT = Path(__file__).resolve().parent


def box(x, y, z, dx, dy, dz):
    return cq.Workplane("XY").box(dx, dy, dz, centered=False).translate((x,y,z))


def export_step(shape, filename):
    path = ROOT / filename
    cq.exporters.export(shape, str(path))
    # Only normalize non-geometric header metadata and whitespace for stable fixtures.
    text = path.read_text()
    text = re.sub(r"(FILE_NAME\('Open CASCADE Shape Model',)'[^']+'", r"\1'2000-01-01T00:00:00'", text, count=1)
    path.write_text("\n".join(line.rstrip() for line in text.splitlines()) + "\n")


def main():
    floor = box(0,0,0,10,6,1)
    wall = box(0,0,1,1,6,4)
    lip = box(1,0,4,2,6,1)
    open_fixed = floor.union(wall).union(lip)
    closed_fixed = open_fixed.union(box(3.5,0,1,1,6,4))
    moving = box(1.5,2,3,1,2,.8)
    export_step(moving, "moving.step")
    for name, fixed in (("open", open_fixed), ("blocked", closed_fixed)):
        export_step(fixed, f"fixed_{name}.step")
        cq.exporters.export(fixed, str(ROOT / f"fixed_{name}.stl"), tolerance=.02, angularTolerance=.1)

        def artifact(filename, frame):
            return {"path": filename, "sha256": hashlib.sha256((ROOT/filename).read_bytes()).hexdigest(), "frame": frame}

        manifest = {
            "schema_version": 1, "name": f"synthetic_{name}_translation", "units": "mm",
            "assembly_to_print": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],
            "artifacts": {"fixed": artifact(f"fixed_{name}.step", "assembly"),
                          "moving": artifact("moving.step", "assembly"),
                          "print_mesh": artifact(f"fixed_{name}.stl", "print"),
                          "profile": artifact("analysis_profile.ini", "configuration")},
            "path_check": {"kind": "sampled_translation", "frame": "assembly",
                           "waypoints_mm": [[0,0,0],[3,0,0],[3,0,4]], "max_step_mm": .1,
                           "volume_tolerance_mm3": 1e-7,
                           "expected_outcome": "sampled_clear" if name == "open" else "collision_found"},
            "slicing": {"engine": "PrusaSlicer", "expected_version": "2.9.2", "center_mm": [90,90], "support_mode": "auto"}}
        (ROOT / f"{name}.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
