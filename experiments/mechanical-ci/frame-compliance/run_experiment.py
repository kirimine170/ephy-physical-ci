#!/usr/bin/env python3
"""Synthetic U-frame compliance experiment. No calibrated retention prediction.

Python standard library only; Gmsh and CalculiX are external, explicit CLI tools.
The fixture has independently chosen dimensions and contains no product CAD.
"""
from __future__ import annotations

import argparse
import hashlib
import platform
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

DIMENSIONS = {"width_mm": 42.0, "length_mm": 58.0,
              "rail_width_mm": 3.2, "thickness_mm": 4.5}
DEFAULT_MESH_SIZES = [3.2, 2.1, 1.4]
ABAQUS_ORDER = (0, 1, 2, 3, 4, 5, 6, 7, 9, 8)
GMSH_EDGES = ((0, 1), (1, 2), (2, 0), (3, 0), (3, 2), (3, 1))


class ExperimentError(RuntimeError):
    """A bounded, user-readable failure without private execution paths."""


def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def scale(a, factor):
    return tuple(x * factor for x in a)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2],
            a[0]*b[1]-a[1]*b[0])


def norm(a):
    return math.sqrt(dot(a, a))


def sum_vectors(vectors):
    result = (0.0, 0.0, 0.0)
    for vector in vectors:
        result = add(result, vector)
    return result


def check(condition, message):
    if not condition:
        raise ExperimentError(message)


def geometry_text(h):
    """Three fused boxes make an intentionally simple, uncalibrated toy U."""
    w, length, b, t = (DIMENSIONS[key] for key in
                       ("width_mm", "length_mm", "rail_width_mm", "thickness_mm"))
    return f'''// Independently specified synthetic geometry; all lengths in mm.
SetFactory("OpenCASCADE");
Box(1) = {{ {-w/2}, 0, 0, {b}, {length}, {t} }};
Box(2) = {{ {w/2-b}, 0, 0, {b}, {length}, {t} }};
Box(3) = {{ {-w/2}, {length-b}, 0, {w}, {b}, {t} }};
fused[] = BooleanUnion{{ Volume{{1}}; Delete; }}{{ Volume{{2,3}}; Delete; }};
Mesh.MeshSizeMin = {h};
Mesh.MeshSizeMax = {h};
Mesh.MeshSizeFromPoints = 0;
Mesh.MeshSizeFromCurvature = 0;
Mesh.MeshSizeExtendFromBoundary = 0;
Mesh.Algorithm3D = 1;
Mesh.ElementOrder = 2;
Mesh.MshFileVersion = 2.2;
Mesh.Binary = 0;
Mesh.SaveAll = 1;
General.NumThreads = 1;
'''


def read_mesh(path):
    """Read the ASCII MSH 2.2 subset used here; reject invalid/linear meshes."""
    check(path.is_file(), "Gmsh did not create a new mesh file.")
    lines = path.read_text().splitlines()
    check(len(lines) >= 3 and lines[0] == "$MeshFormat" and
          lines[1].split()[:2] == ["2.2", "0"], "Expected ASCII MSH 2.2.")
    nodes, triangles, tets = {}, [], []
    try:
        start = lines.index("$Nodes")
        count = int(lines[start+1])
        for line in lines[start+2:start+2+count]:
            values = line.split()
            node = int(values[0])
            check(node not in nodes, "Duplicate mesh node.")
            nodes[node] = tuple(float(value) for value in values[1:4])
        check(lines[start+2+count] == "$EndNodes", "Incomplete node block.")
        start = lines.index("$Elements")
        count = int(lines[start+1])
        for line in lines[start+2:start+2+count]:
            values = list(map(int, line.split()))
            number, kind, ntags = values[:3]
            row = values[3+ntags:]
            if kind == 9:
                check(len(row) == 6, "Invalid triangle6 connectivity.")
                triangles.append(tuple(row))
            elif kind == 11:
                check(len(row) == 10, "Invalid tetra10 connectivity.")
                tets.append((number, tuple(row)))
            elif kind in (4, 5, 6, 7, 12, 13, 14):
                raise ExperimentError("Expected only quadratic tetrahedra in the volume.")
        check(lines[start+2+count] == "$EndElements", "Incomplete element block.")
    except (ValueError, IndexError, KeyError) as error:
        raise ExperimentError("Malformed MSH file.") from error
    check(nodes and triangles and tets, "Mesh is missing nodes, faces, or tetrahedra.")
    check(all(len(point) == 3 and all(math.isfinite(x) for x in point)
              for point in nodes.values()), "Nonfinite or malformed mesh coordinates.")
    check(all(n in nodes for _, cell in tets for n in cell) and
          all(n in nodes for cell in triangles for n in cell), "Unknown connectivity node.")
    return nodes, triangles, tets


def mesh_quality(nodes, tets):
    volumes, qualities, midpoint_error = [], [], 0.0
    for _, row in tets:
        p = [nodes[n] for n in row]
        volume = dot(sub(p[1], p[0]), cross(sub(p[2], p[0]), sub(p[3], p[0])))/6
        check(volume > 0, "Nonpositive tetrahedral Jacobian.")
        volumes.append(volume)
        edge_square_sum = sum(dot(sub(p[a], p[b]), sub(p[a], p[b]))
                              for a in range(4) for b in range(a+1, 4))
        qualities.append(12*(3*volume)**(2/3)/edge_square_sum)
        for index, (a, b) in enumerate(GMSH_EDGES):
            midpoint_error = max(midpoint_error, norm(sub(p[4+index], scale(add(p[a], p[b]), .5))))
    check(midpoint_error < 1e-7, "Unexpected curved element or tetra10 node ordering.")
    w, length, b, t = (DIMENSIONS[key] for key in
                       ("width_mm", "length_mm", "rail_width_mm", "thickness_mm"))
    expected = (2*b*length + (w-2*b)*b)*t
    volume_error = abs(sum(volumes)-expected)/expected
    check(volume_error < 1e-8, "Mesh volume disagrees with synthetic CAD volume.")
    return {"nodes": len(nodes), "tetra10_elements": len(tets),
            "volume_mm3": sum(volumes), "expected_volume_mm3": expected,
            "relative_volume_error": volume_error,
            "minimum_positive_tetra_volume_mm3": min(volumes),
            "minimum_mean_ratio_quality": min(qualities),
            "nonpositive_jacobians": 0, "max_midside_coordinate_error_mm": midpoint_error}


def load_weights(nodes, triangles):
    """Consistent constant shear traction on both y=0 end faces.

    Triangle6 integrated shape functions are 0 at corners and A/3 at midsides.
    The applied force is along X, although the loaded face normal is along Y.
    """
    areas = {"left": 0.0, "right": 0.0}
    weights = {"left": {}, "right": {}}
    for row in triangles:
        if not all(abs(nodes[n][1]) < 1e-8 for n in row):
            continue
        side = "left" if sum(nodes[n][0] for n in row[:3]) < 0 else "right"
        a, b, c = [nodes[n] for n in row[:3]]
        area = norm(cross(sub(b, a), sub(c, a)))/2
        areas[side] += area
        for n in row[3:]:
            weights[side][n] = weights[side].get(n, 0.0)+area/3
    expected = DIMENSIONS["rail_width_mm"]*DIMENSIONS["thickness_mm"]
    for side in areas:
        check(abs(areas[side]-expected) < 1e-7, "Missing or incorrect loaded end face.")
        weights[side] = {n: weight/areas[side] for n, weight in weights[side].items()}
    return weights, areas


def make_forces(weights, force_each):
    result = {}
    for side, sign in (("left", -1), ("right", 1)):
        for n, weight in weights[side].items():
            result[n] = (sign*force_each*weight, 0.0, 0.0)
    return result


def supports(nodes, kind):
    w, length, b = (DIMENSIONS[key] for key in
                    ("width_mm", "length_mm", "rail_width_mm"))
    if kind == "rear_clamp":
        return {(n, direction) for n, point in nodes.items() if point[1] >= length-b-1e-8
                for direction in (1, 2, 3)}
    check(kind == "free_gauge", "Unknown support condition.")
    anchors = (((-w/2, length, 0), (1, 2, 3)),
               ((w/2, length, 0), (2, 3)),
               ((-w/2+b, length-b, 0), (3,)))
    bc = set()
    for target, directions in anchors:
        found = [n for n, point in nodes.items() if norm(sub(point, target)) < 1e-8]
        check(len(found) == 1, "Gauge vertex not uniquely present in mesh.")
        bc.update((found[0], direction) for direction in directions)
    check(len(bc) == 6, "Gauge support must constrain exactly six DOFs.")
    return bc


def write_deck(path, nodes, tets, bc, forces, young, poisson):
    with path.open("w") as out:
        out.write("*HEADING\nSynthetic U-frame; N mm MPa; uncalibrated linear diagnostic\n")
        out.write("*NODE,NSET=ALLN\n")
        for n, point in sorted(nodes.items()):
            out.write(f"{n},"+",".join(f"{x:.14g}" for x in point)+"\n")
        out.write("*ELEMENT,TYPE=C3D10,ELSET=BODY\n")
        for number, row in tets:
            out.write(f"{number},"+",".join(str(row[i]) for i in ABAQUS_ORDER)+"\n")
        out.write(f"*MATERIAL,NAME=SYNTHETIC\n*ELASTIC\n{young:.14g},{poisson:.14g}\n")
        out.write("*SOLID SECTION,ELSET=BODY,MATERIAL=SYNTHETIC\n*BOUNDARY\n")
        for n, direction in sorted(bc):
            out.write(f"{n},{direction},{direction},0\n")
        out.write("*STEP\n*STATIC\n*CLOAD\n")
        for n, vector in sorted(forces.items()):
            for direction, value in enumerate(vector, 1):
                if value:
                    out.write(f"{n},{direction},{value:.14g}\n")
        out.write("*NODE PRINT,NSET=ALLN\nU,RF\n*END STEP\n")


def parse_results(path):
    check(path.is_file(), "CalculiX did not create a new result file.")
    displacement, force, target = {}, {}, None
    for line in path.read_text().splitlines():
        if "displacements (vx,vy,vz)" in line:
            target = displacement
        elif "forces (fx,fy,fz)" in line:
            target = force
        elif target is not None and re.match(r"^\s*\d+\s+[-+0-9.]", line):
            values = line.split()
            try:
                target[int(values[0])] = tuple(float(x) for x in values[1:4])
            except ValueError as error:
                raise ExperimentError("Malformed solver result row.") from error
    check(displacement and force, "Solver output has no displacement or force field.")
    check(all(len(v) == 3 and all(math.isfinite(x) for x in v)
              for field in (displacement, force) for v in field.values()),
          "Nonfinite or malformed solver field.")
    return displacement, force


def summarize_case(nodes, bc, forces, weights, displacement, nodal_force, load, kind, young):
    check(set(displacement) == set(nodes) and set(nodal_force) == set(nodes),
          "Solver result does not cover every mesh node.")
    reactions = {n: tuple(nodal_force[n][i] if (n, i+1) in bc else 0.0 for i in range(3))
                 for n in nodes}
    applied = sum_vectors(forces.values())
    applied_moment = sum_vectors(cross(nodes[n], vector) for n, vector in forces.items())
    reaction = sum_vectors(reactions.values())
    reaction_moment = sum_vectors(cross(nodes[n], vector) for n, vector in reactions.items())
    force_residual = add(applied, reaction)
    moment_residual = add(applied_moment, reaction_moment)
    max_reaction = max(abs(nodal_force[n][direction-1]) for n, direction in bc)
    gap = (sum(weight*displacement[n][0] for n, weight in weights["right"].items())-
           sum(weight*displacement[n][0] for n, weight in weights["left"].items()))
    energy = .5*sum(dot(vector, displacement[n]) for n, vector in forces.items())
    check(gap > 0 and energy > 0, "Opening displacement and strain energy must be positive.")
    force_tol = load*1e-4
    moment_tol = load*DIMENSIONS["length_mm"]*1e-4
    check(max(map(abs, applied)) < load*1e-10 and
          max(map(abs, applied_moment)) < load*DIMENSIONS["length_mm"]*1e-10,
          "Applied opening loads are not self-equilibrated.")
    check(max(map(abs, force_residual)) < force_tol, "Force equilibrium check failed.")
    check(max(map(abs, moment_residual)) < moment_tol, "Moment equilibrium check failed.")
    if kind == "free_gauge":
        check(max_reaction < load*1e-6, "Gauge constraint is carrying a significant reaction.")
    return {"support": kind, "youngs_modulus_MPa": young, "load_each_side_N": load,
            "gap_increase_mm": gap, "gap_compliance_mm_per_N_each_side": gap/load,
            "maximum_displacement_mm": max(map(norm, displacement.values())),
            "strain_energy_Nmm": energy, "constrained_DOFs": len(bc),
            "applied_force_N": applied, "applied_moment_Nmm": applied_moment,
            "support_reaction_N": reaction, "support_reaction_moment_Nmm": reaction_moment,
            "force_residual_N": force_residual, "moment_residual_Nmm": moment_residual,
            "maximum_individual_support_reaction_N": max_reaction,
            "force_tolerance_N": force_tol, "moment_tolerance_Nmm": moment_tol,
            "checks_passed": True}


def execute(command, cwd, timeout, label, accepted_codes=(0,)):
    try:
        run = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ExperimentError(f"{label} could not run ({type(error).__name__}).") from error
    check(run.returncode in accepted_codes, f"{label} exited with status {run.returncode}.")
    return run.stdout+run.stderr


def resolve_tool(value, label):
    resolved = shutil.which(value)
    check(resolved is not None, f"{label} executable not found; provide its CLI argument.")
    return str(Path(resolved).resolve())


def detect_version(tool, flag, timeout, label):
    # CCX 2.23 prints a valid version and exits 201 for -v; solver runs still require 0.
    text = execute([tool, flag], None, timeout, label,
                   accepted_codes=(0, 201) if label == "CalculiX" else (0,))
    pattern = r"(?:Version|version|^|\n)\s*[:=]?\s*(\d+\.\d+(?:\.\d+)?)"
    match = re.search(pattern, text)
    check(match is not None, f"Could not identify {label} version.")
    return match.group(1)


def solve(ccx, folder, nodes, tets, weights, load, young, poisson, kind, name, timeout):
    bc = supports(nodes, kind)
    forces = make_forces(weights, load)
    write_deck(folder/f"{name}.inp", nodes, tets, bc, forces, young, poisson)
    log = execute([ccx, "-i", name], folder, timeout, "CalculiX")
    (folder/f"{name}.log").write_text(log)
    check("Job finished" in log and "*ERROR" not in log, "CalculiX did not finish cleanly.")
    displacement, nodal_force = parse_results(folder/f"{name}.dat")
    result = summarize_case(nodes, bc, forces, weights, displacement, nodal_force, load, kind, young)
    result["input_deck_sha256"] = hashlib.sha256((folder/f"{name}.inp").read_bytes()).hexdigest()
    result["solver_warning_count"] = log.count("*WARNING")
    check(result["solver_warning_count"] == 0, "CalculiX emitted a warning; inspect the local log.")
    return result



def new_output_directory(path):
    """A fresh root prevents overwrite and accidental reuse of stale solver files."""
    target = path.absolute()  # Do not resolve away a final symlink before checking it.
    check(not target.exists() and not target.is_symlink(),
          "Output directory must be new and must not be a symlink.")
    try:
        target.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        raise ExperimentError("Could not create a new output directory.") from error
    return target


def run_experiment(args):
    check(not args.output.exists() and not args.output.is_symlink(),
          "Output directory must be new and must not be a symlink.")
    gmsh = resolve_tool(args.gmsh, "Gmsh")
    ccx = resolve_tool(args.ccx, "CalculiX")
    versions = {"gmsh": detect_version(gmsh, "--version", args.timeout, "Gmsh"),
                "calculix": detect_version(ccx, "-v", args.timeout, "CalculiX")}
    output = new_output_directory(args.output)
    results = []
    for index, h in enumerate(args.mesh_sizes):
        folder = output/f"mesh_{index+1}"
        folder.mkdir(exist_ok=False)
        (folder/"fixture.geo").write_text(geometry_text(h))
        log = execute([gmsh, "fixture.geo", "-3", "-order", "2", "-format", "msh2",
                       "-o", "fixture.msh", "-v", "2", "-nt", "1"], folder, args.timeout, "Gmsh")
        (folder/"gmsh.log").write_text(log)
        check("Error" not in log, "Gmsh emitted an error; inspect the local log.")
        nodes, triangles, tets = read_mesh(folder/"fixture.msh")
        quality = mesh_quality(nodes, tets)
        weights, areas = load_weights(nodes, triangles)
        cases = [solve(ccx, folder, nodes, tets, weights, args.load, args.young, args.poisson,
                       kind, kind, args.timeout) for kind in ("free_gauge", "rear_clamp")]
        results.append({"mesh_size_mm": h, "mesh": quality, "loaded_face_area_mm2": areas,
                        "synthetic_geo_sha256": hashlib.sha256((folder/"fixture.geo").read_bytes()).hexdigest(),
                        "synthetic_mesh_sha256": hashlib.sha256((folder/"fixture.msh").read_bytes()).hexdigest(),
                        "cases": cases})
        print(f"mesh {index+1}/{len(args.mesh_sizes)}: {quality['tetra10_elements']} quadratic tetrahedra", flush=True)
    half = solve(ccx, folder, nodes, tets, weights, args.load, args.young/2, args.poisson,
                 "free_gauge", "free_gauge_half_E", args.timeout)
    finest = results[-1]["cases"]
    convergence = {}
    for i, kind in enumerate(("free_gauge", "rear_clamp")):
        values = [result["cases"][i]["gap_compliance_mm_per_N_each_side"] for result in results]
        change = abs(values[-1]-values[-2])/abs(values[-1])
        convergence[kind] = {"gap_compliance_mm_per_N_each_side": values,
                             "relative_change_last_two_meshes": change,
                             "limit": args.convergence_limit, "passed": change < args.convergence_limit}
    modulus_ratio = half["gap_compliance_mm_per_N_each_side"]/finest[0]["gap_compliance_mm_per_N_each_side"]
    support_ratio = finest[0]["gap_compliance_mm_per_N_each_side"]/finest[1]["gap_compliance_mm_per_N_each_side"]
    summary = {"schema_version": 1, "fixture": "independently_dimensioned_synthetic_U_frame",
               "units": {"length": "mm", "force": "N", "modulus": "MPa"},
               "dimensions": DIMENSIONS, "tool_versions": versions,
               "python_version": platform.python_version(),
               "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "material": {"calibrated": False, "model": "synthetic_isotropic_linear_elastic",
                            "E_MPa": args.young, "poisson_ratio": args.poisson},
               "load": {"each_side_N": args.load, "sum_force_magnitudes_N": 2*args.load,
                        "direction": "opposite outward X shear traction on y=0 end faces",
                        "normalization": "total right-minus-left gap per N applied to EACH side"},
               "boundary_conditions": {
                   "free_gauge": "Six 3-2-1 DOFs remove rigid-body motion; individual reactions checked near zero.",
                   "rear_clamp": "All XYZ DOFs with y >= length - rail_width are fixed; artificial stiff support."},
               "meshes": results, "convergence": convergence,
               "E_halved_case": half, "E_halved_compliance_ratio": modulus_ratio,
               "free_to_clamped_compliance_ratio": support_ratio,
               "not_modeled": ["product geometry", "base or board", "contact", "friction", "print beads",
                               "layer bonding", "calibrated material", "large deformation", "failure", "retention force"],
               "checks_passed": all(item["passed"] for item in convergence.values()) and
                                abs(modulus_ratio-2) < 1e-5 and support_ratio > 1}
    summary["validation_scope"] = {
        "synthetic_geometry_and_element_checks": "pass",
        "synthetic_force_moment_equilibrium": "pass",
        "free_gauge_individual_reactions": "pass",
        "synthetic_mesh_refinement": "pass" if all(x["passed"] for x in convergence.values()) else "fail",
        "synthetic_modulus_scaling": "pass" if abs(modulus_ratio-2) < 1e-5 else "fail",
        "physical_material_calibration": "unknown",
        "physical_contact_and_friction": "unknown",
        "physical_retention_or_failure_load": "unknown"}
    (output/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    (output/"compact_summary.json").write_text(json.dumps(compact_summary(summary), indent=2)+"\n")
    check(summary["checks_passed"], "Convergence, modulus scaling, or support comparison check failed.")
    return summary



def compact_summary(summary):
    """Whitelist portable synthetic evidence; exclude commands, paths and raw fields."""
    keys = ("schema_version", "fixture", "units", "dimensions", "tool_versions", "python_version",
            "generator_sha256", "material", "load", "boundary_conditions", "convergence",
            "E_halved_compliance_ratio", "free_to_clamped_compliance_ratio", "validation_scope",
            "not_modeled", "checks_passed")
    compact = {key: summary[key] for key in keys}
    compact["hash_algorithm"] = "sha256"
    compact["meshes"] = []
    for mesh in summary["meshes"]:
        compact["meshes"].append({
            "mesh_size_mm": mesh["mesh_size_mm"], "mesh_quality": mesh["mesh"],
            "synthetic_geo_sha256": mesh["synthetic_geo_sha256"],
            "synthetic_mesh_sha256": mesh["synthetic_mesh_sha256"],
            "cases": [{key: case[key] for key in (
                "support", "load_each_side_N", "gap_increase_mm", "gap_compliance_mm_per_N_each_side",
                "constrained_DOFs", "force_residual_N", "moment_residual_Nmm",
                "maximum_individual_support_reaction_N", "input_deck_sha256", "checks_passed")}
                for case in mesh["cases"]]})
    return compact


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--gmsh", required=True, help="Existing Gmsh CLI executable; no download/install is performed")
    result.add_argument("--ccx", required=True, help="Existing CalculiX CLI executable")
    result.add_argument("--output", required=True, type=Path, help="Local generated-output directory")
    result.add_argument("--mesh-sizes", nargs="+", type=float, default=DEFAULT_MESH_SIZES)
    result.add_argument("--load", type=float, default=.005, help="Outward force on EACH side, N")
    result.add_argument("--young", type=float, default=1500., help="Synthetic E, MPa")
    result.add_argument("--poisson", type=float, default=.3)
    result.add_argument("--convergence-limit", type=float, default=.02)
    result.add_argument("--timeout", type=float, default=180.)
    return result


def validate_args(args):
    check(len(args.mesh_sizes) >= 2 and all(math.isfinite(x) and x > 0 for x in args.mesh_sizes),
          "Provide at least two positive finite mesh sizes.")
    check(all(a > b for a, b in zip(args.mesh_sizes, args.mesh_sizes[1:])),
          "Mesh sizes must be strictly decreasing.")
    check(all(math.isfinite(x) and x > 0 for x in
              (args.load, args.young, args.timeout, args.convergence_limit)), "Positive finite parameters required.")
    check(math.isfinite(args.poisson) and -1 < args.poisson < .5, "Require -1 < Poisson ratio < 0.5.")


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        validate_args(args)
        summary = run_experiment(args)
    except ExperimentError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"checks_passed": summary["checks_passed"],
                      "free_to_clamped_compliance_ratio": summary["free_to_clamped_compliance_ratio"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
