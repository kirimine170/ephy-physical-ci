"""Conservative parser for Prusa-style, single-extruder linear toolpaths.

This extracts intended paths, not deposited material geometry or strength.
"""
import collections
import math
import re

from . import UNIMPLEMENTED_GATES, __version__
from .errors import InputError

TOKEN = re.compile(r"([A-Z])([-+]?(?:\d+(?:\.\d*)?|\.\d+))")
ALLOWED_M = {"M73", "M82", "M83", "M84", "M104", "M106", "M107", "M109", "M140", "M190", "M201", "M203", "M204", "M205", "M220", "M300", "M400"}
UNSUPPORTED_G = {"G2", "G3", "G10", "G11", "G20", "G28", "G30", "G53", "G54", "G55", "G56", "G57", "G58", "G59", "G90.1", "G91", "G91.1", "G92.1"}


def extract(text):
    position = dict.fromkeys("XYZE", None)
    absolute_xyz = units_mm = False
    absolute_e = None
    role, width, height = "Unknown", None, None
    segments, z_planes = [], set()
    retract_debt = stationary_extrusion = 0.
    for line_number, raw in enumerate(text.splitlines(), 1):
        for prefix, variable in ((";WIDTH:", "width"), (";HEIGHT:", "height"), (";Z:", "z")):
            if raw.startswith(prefix):
                try:
                    value = float(raw[len(prefix):])
                except ValueError as error:
                    raise InputError(f"invalid {variable} metadata at line {line_number}") from error
                if not math.isfinite(value) or variable != "z" and value <= 0:
                    raise InputError(f"invalid {variable} metadata at line {line_number}")
                if variable == "width": width = value
                elif variable == "height": height = value
                else: z_planes.add(value)
        if raw.startswith(";TYPE:"):
            role = raw[6:].strip() or "Unknown"
        code = raw.split(";", 1)[0].strip()
        if not code:
            continue
        if "(" in code or "*" in code or re.match(r"N\d", code):
            raise InputError(f"unsupported G-code dialect at line {line_number}")
        command_match = re.match(r"^([GMT]\d+(?:\.\d+)?)(?:\s|$)", code)
        if not command_match:
            raise InputError(f"unsupported command syntax at line {line_number}")
        command = command_match.group(1)
        if command in UNSUPPORTED_G or command.startswith("T") or command == "M200":
            raise InputError(f"unsupported motion/extrusion mode {command} at line {line_number}")
        if command.startswith("M") and command not in ALLOWED_M:
            raise InputError(f"unsupported M command {command} at line {line_number}")
        if command.startswith("G") and command not in {"G0", "G1", "G4", "G21", "G90", "G92"}:
            raise InputError(f"unsupported G command {command} at line {line_number}")
        if command == "G21": units_mm = True
        if command == "G90":
            absolute_xyz = True
            absolute_e = None  # Require an explicit extrusion mode after coordinate-mode changes.
        if command == "M82": absolute_e = True
        if command == "M83": absolute_e = False
        if command not in {"G0", "G1", "G92"}:
            continue
        rest = code[command_match.end():]
        chunks = rest.split()
        if not all(TOKEN.fullmatch(chunk) for chunk in chunks):
            raise InputError(f"coordinates must be spaced decimal tokens at line {line_number}")
        tokens = [TOKEN.fullmatch(chunk).groups() for chunk in chunks]
        if len(tokens) != len({key for key, _ in tokens}):
            raise InputError(f"malformed or repeated coordinate at line {line_number}")
        args = {key: float(value) for key, value in tokens}
        if any(key not in "XYZEF" for key in args) or not all(math.isfinite(v) for v in args.values()):
            raise InputError(f"unsupported/nonfinite coordinate at line {line_number}")
        if not units_mm or not absolute_xyz:
            raise InputError("G21 and G90 must precede coordinate commands")
        if "E" in args and absolute_e is None:
            raise InputError("M82 or M83 must establish the extrusion mode")
        if command == "G92":
            if set(args) != {"E"}:
                raise InputError("only G92 E resets are supported; XYZ offsets are ambiguous")
            position.update({key: value for key, value in args.items() if key in position})
            continue
        previous = position.copy()
        position.update({key: value for key, value in args.items() if key in "XYZ"})
        if "E" in args and absolute_e and previous["E"] is None:
            raise InputError("absolute extrusion requires an explicit G92 E baseline")
        de = ((args["E"] - previous["E"]) if absolute_e else args["E"]) if "E" in args else 0.
        if not math.isfinite(de):
            raise InputError("extrusion arithmetic overflow")
        if previous["E"] is not None:
            position["E"] = previous["E"] + de
            if not math.isfinite(position["E"]):
                raise InputError("extrusion arithmetic overflow")
        if de <= 0:
            retract_debt -= de
            continue
        recovered = min(retract_debt, de)
        retract_debt -= recovered
        deposited = de - recovered
        if deposited <= 1e-9:
            continue
        if not any(k in args for k in "XYZ"):
            stationary_extrusion += deposited
            continue
        if any(previous[k] is None or position[k] is None for k in "XYZ"):
            raise InputError("establish all XYZ coordinates before moving extrusion")
        distance = math.dist([previous[k] for k in "XYZ"], [position[k] for k in "XYZ"])
        if not math.isfinite(distance):
            raise InputError("coordinate arithmetic overflow")
        if distance <= 1e-9:
            stationary_extrusion += deposited
            continue
        # A mixed unretract/extrude move is partitioned assuming uniform E per distance.
        start = [previous[k] + (position[k]-previous[k])*recovered/de for k in "XYZ"]
        end = [position[k] for k in "XYZ"]
        segments.append({"line": line_number, "role": role, "from_mm": start, "to_mm": end,
                         "length_mm": math.dist(start,end), "filament_delta_mm": deposited,
                         "width_mm": width, "height_mm": height,
                         "xy_heading_deg": math.degrees(math.atan2(end[1]-start[1],end[0]-start[0]))})
    if not segments:
        raise InputError("no supported moving-extrusion paths found")
    counts = collections.Counter(segment["role"] for segment in segments)
    lengths = collections.defaultdict(float)
    for segment in segments:
        lengths[segment["role"]] += segment["length_mm"]
    widths = [s["width_mm"] for s in segments if s["width_mm"] is not None]
    missing = sum(s["width_mm"] is None or s["height_mm"] is None or s["role"] in ("Unknown", "Custom") for s in segments)
    summary = {"schema_version": 1, "tool_version": __version__, "command": "analyze-gcode",
               "units": "mm", "frame": "gcode_machine_coordinates", "extrusion_segments": len(segments),
               "segments_by_role": dict(counts), "length_mm_by_role": dict(lengths),
               "z_planes_mm": sorted(z_planes), "unique_z_planes": len(z_planes),
               "width_range_mm": [min(widths),max(widths)] if widths else None,
               "segments_with_incomplete_metadata": missing, "stationary_extrusion_mm": stationary_extrusion,
               "physical_validation": "not_performed", "unimplemented_gates": dict(UNIMPLEMENTED_GATES),
               "limits": ["Intended extrusion paths are not material volume, bonding, or strength.",
                          "Support paths do not prove support removal or post-removal function.",
                          "Extrusion widths/heights are slicer metadata, not measurements.",
                          "This is a deliberately limited linear single-extruder dialect."]}
    return summary, segments
