"""Generate original toy solids, never import a product CAD model."""
import argparse
from pathlib import Path
import re
import cadquery as cq


def build(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    outer = cq.Solid.makeBox(8, 8, 8, cq.Vector(-4, -4, 0))
    shapes = {
        "open": outer.cut(cq.Solid.makeBox(6, 6, 8, cq.Vector(-3, -3, 1))),
        "closed": outer.cut(cq.Solid.makeBox(6, 6, 6, cq.Vector(-3, -3, 1))),
        "moving": cq.Solid.makeBox(2, 2, 2, cq.Vector(-1, -1, 2)),
    }
    for name, shape in shapes.items():
        if not shape.isValid() or len(shape.Solids()) != 1:
            raise RuntimeError("invalid synthetic fixture")
        path = output / (name + ".step")
        cq.exporters.export(shape, str(path))
        text = path.read_text()
        text = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", "2000-01-01T00:00:00", text)
        path.write_text("\n".join(line.rstrip() for line in text.splitlines()) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new directory; existing paths are rejected")
    build(parser.parse_args().output)
