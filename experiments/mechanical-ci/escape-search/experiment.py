"""Finite connected mesh exploration followed by independent frozen-STEP replay.

Research prototype: the only goal is the entire moving bounding box above the
fixed bounding box. A missing path never means retention or mechanical safety.
"""
import argparse
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import sys

import cadquery as cq
import fcl
import numpy as np
from scipy.spatial.transform import Rotation

POSE_ORDER = ["dx_mm", "dy_mm", "dz_mm", "roll_deg", "pitch_deg", "yaw_deg"]
LIMITS = np.array([[-4, 4], [-4, 4], [0, 10], [-30, 30], [-30, 30], [-30, 30]], float)
VOLUME_TOLERANCE = 1e-7


def read_solid(path):
    roots = cq.importers.importStep(str(path)).vals()
    solids = [solid for root in roots for solid in root.Solids()]
    if len(roots) != 1 or len(solids) != 1 or not solids[0].isValid():
        raise ValueError("each input must contain exactly one valid solid and no extra STEP roots")
    return solids[0]


def corners(shape):
    b = shape.BoundingBox()
    return np.array([[x, y, z] for x in (b.xmin, b.xmax)
                     for y in (b.ymin, b.ymax) for z in (b.zmin, b.zmax)])


def pose_matrix(q, pivot):
    rotation = Rotation.from_euler("xyz", q[3:], degrees=True).as_matrix()
    return rotation, pivot + q[:3] - rotation @ pivot


def step_count(a, b, radius, step):
    """Upper bound on each point's travel for Euler-linear interpolation.

    This bounds displacement between checked poses; it does NOT prove a swept
    volume is collision-free. Euler increments are not shortest-path rotations.
    """
    if not math.isfinite(step) or step <= 0:
        raise ValueError("point step must be finite and positive")
    bound = np.linalg.norm(b[:3] - a[:3]) + radius * np.deg2rad(np.abs(b[3:] - a[3:]).sum())
    count = max(1, math.ceil(float(bound) / step))
    if count > 10000:
        raise ValueError("edge exceeds the 10000-sample budget")
    return count


def sample_edge(a, b, radius, step):
    count = step_count(a, b, radius, step)
    return (a + (b - a) * i / count for i in range(1, count + 1))


def mesh_object(shape):
    vertices, triangles = shape.tessellate(0.005, 0.05)
    points = np.array([v.toTuple() for v in vertices], float)
    model = fcl.BVHModel()
    model.beginModel(len(points), len(triangles))
    model.addSubModel(points, np.asarray(triangles, dtype=np.int32))
    model.endModel()
    return fcl.CollisionObject(model), len(triangles)


def backtrack(states, parents, index):
    path = []
    while index >= 0:
        path.append(states[index])
        parent = parents[index]
        if parent >= index or parent < -1 or index > 0 and parent == -1:
            raise ValueError("tree is not rooted or contains a cycle")
        index = parent
    return path[::-1]


def transform_brep(shape, q, pivot):
    result = shape
    for axis, angle in zip(np.eye(3), q[3:]):
        result = result.rotate(tuple(pivot), tuple(pivot + axis), float(angle))
    return result.translate(tuple(q[:3]))


def replay(fixed_path, moving_path, path, pivot, point_step):
    # Re-import frozen bytes. Do not reuse search BRep objects or meshes.
    fixed, moving = read_solid(fixed_path), read_solid(moving_path)
    radius = np.linalg.norm(corners(moving) - pivot, axis=1).max()
    checked, maximum, witness = 0, 0.0, None
    poses = [path[0]]
    for a, b in zip(path, path[1:]):
        poses.extend(sample_edge(np.asarray(a), np.asarray(b), radius, point_step))
    for q in poses:
        volume = fixed.intersect(transform_brep(moving, q, pivot)).Volume()
        if not math.isfinite(volume):
            raise RuntimeError("nonfinite BRep overlap volume")
        checked += 1
        maximum = max(maximum, volume)
        if volume > VOLUME_TOLERANCE:
            witness = {"q": np.asarray(q).tolist(), "overlap_mm3": volume}
            break
    return {"independently_reimported_STEP": True, "samples_checked": checked,
            "sampled_clear": witness is None, "first_collision": witness,
            "max_overlap_mm3": maximum, "point_step_mm": point_step,
            "continuous_collision_certified": False}


def run(fixed_path, moving_path, seed=17, proposals=500, point_step=0.2, replay_step=0.1):
    if type(proposals) is not int or not 1 <= proposals <= 200000:
        raise ValueError("proposals must be 1..200000")
    if not 0.001 <= point_step <= 1 or not 0.001 <= replay_step <= point_step:
        raise ValueError("require 0.001 <= replay step <= search step <= 1 mm")
    files = [Path(fixed_path), Path(moving_path)]
    hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in files]
    fixed, moving = [read_solid(p) for p in files]
    moving_corners = corners(moving)
    pivot = moving_corners.mean(axis=0)
    radius = float(np.linalg.norm(moving_corners - pivot, axis=1).max())
    goal_z = fixed.BoundingBox().zmax + 0.01
    # Prevent the specific old audit failure: a declared goal beyond all bounds.
    if moving_corners[:, 2].min() + LIMITS[2, 1] <= goal_z:
        raise ValueError("above-body goal is unreachable even at the translation bound")
    initial_volume = fixed.intersect(moving).Volume()
    if not math.isfinite(initial_volume) or initial_volume > VOLUME_TOLERANCE:
        raise ValueError("assembled origin overlaps in BRep")
    obstacle, fixed_triangles = mesh_object(fixed)
    mobile, moving_triangles = mesh_object(moving)
    request = fcl.CollisionRequest(num_max_contacts=1, enable_contact=False)
    queries = 0

    def collides(q):
        nonlocal queries
        queries += 1
        rotation, translation = pose_matrix(q, pivot)
        mobile.setTransform(fcl.Transform(rotation, translation))
        return bool(fcl.collide(mobile, obstacle, request, fcl.CollisionResult()))

    def reached(q):
        rotation, translation = pose_matrix(q, pivot)
        return bool(np.min(moving_corners @ rotation.T + translation, axis=0)[2] > goal_z)

    if collides(np.zeros(6)):
        raise ValueError("origin touches mesh boundary; this experiment rejects contact")
    states, parents = [np.zeros(6)], [-1]
    occupied = {tuple(np.zeros(6, dtype=int))}
    bin_width = np.array([.05, .05, .05, 1., 1., 1.])
    rng = np.random.default_rng(seed)
    goal = None
    best = 0
    for attempt in range(1, proposals + 1):
        if rng.random() < .4:
            parent = best
            delta = np.array([0., 0., .8, 0., 0., 0.])
        else:
            parent = int(rng.integers(len(states)))
            delta = rng.normal(size=6) * [.4, .4, .4, 4, 4, 4]
        q = states[parent] + delta
        if np.any(q < LIMITS[:, 0]) or np.any(q > LIMITS[:, 1]):
            continue
        key = tuple(np.floor(q / bin_width).astype(int))
        if key in occupied or collides(q):
            continue
        if any(collides(p) for p in sample_edge(states[parent], q, radius, point_step)):
            continue
        states.append(q)
        parents.append(parent)
        occupied.add(key)
        current = len(states) - 1
        if q[2] > states[best][2]:
            best = current
        if reached(q):
            goal = current
            break
    chosen = goal if goal is not None else best
    path = backtrack(states, parents, chosen)
    validation = replay(*files, path, pivot, replay_step)
    if [hashlib.sha256(p.read_bytes()).hexdigest() for p in files] != hashes:
        raise ValueError("STEP inputs changed during the experiment")
    result = "not_found_in_bounded_search"
    if goal is not None:
        result = "sampled_escape_candidate" if validation["sampled_clear"] else "mesh_candidate_rejected_by_BRep"
    return {"schema_version": "escape-experiment/1", "experiment_version": 1,
            "result": result, "seed": seed, "units": {"length": "mm", "angle": "degree"},
            "gates": {"execution": "pass", "selected_path_samples": "pass" if validation["sampled_clear"] else "fail",
                      "continuous_collision": "unknown", "retention": "unknown", "material_calibration": "not_applicable"},
            "material_scope": "rigid_geometry_only", "boundary_conditions": "fixed obstacle; moving rigid body",
            "proposal_budget": proposals, "proposals_attempted": attempt,
            "connected_nodes": len(states), "mesh_collision_queries": queries,
            "pose_order": POSE_ORDER, "rotation": "Rz(yaw) Ry(pitch) Rx(roll) about initial BBox center",
            "pivot_mm": pivot.tolist(), "radius_bound_mm": radius,
            "bounds": LIMITS.tolist(), "goal": {"kind": "whole_moving_BBox_above_fixed_BBox", "min_z_mm": goal_z},
            "search_point_step_mm": point_step, "overlap_tolerance_mm3": VOLUME_TOLERANCE,
            "input_sha256": {"fixed": hashes[0], "moving": hashes[1]},
            "mesh_triangles": {"fixed": fixed_triangles, "moving": moving_triangles},
            "versions": {p: importlib.metadata.version(p) for p in ("cadquery", "cadquery-ocp", "numpy", "scipy", "python-fcl")},
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "selected_path_kind": "escape_candidate" if goal is not None else "reachable_play_only",
            "selected_tree_path": [p.tolist() for p in path], "selected_path_BRep_replay": validation,
            "selected_tree_nodes": len(path), "whole_graph_BRep_verified": False,
            "retention_proven": False, "physical_validation": "not_performed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixed", type=Path, required=True)
    parser.add_argument("--moving", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new JSON file")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--proposals", type=int, default=500)
    args = parser.parse_args()
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("output already exists")
        result = run(args.fixed, args.moving, args.seed, args.proposals)
        with args.output.open("x") as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write("\n")
        print(result["result"])
        return 0  # experiment completed; result is never a retention pass
    except (ValueError, OSError, RuntimeError) as error:
        print(f"experiment failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
