"""Read-only STL finite-section geometry helpers. No contact or dynamics solver.

Requires numpy, scipy, trimesh, shapely and networkx. All units follow the input mesh.
The caller owns assembly transforms; native STL coordinates are not assumed to
be a valid assembly. Missing/degenerate sections never mean a passing result.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path
import numpy as np
from shapely.geometry import Polygon
import trimesh


def _validate_mesh(mesh):
    if not isinstance(mesh, trimesh.Trimesh) or not len(mesh.vertices) or not len(mesh.faces):
        raise ValueError('A nonempty triangle mesh is required')
    if not np.isfinite(mesh.vertices).all():
        raise ValueError('Mesh vertices must be finite; no automatic repair is applied')
    if np.any(mesh.faces < 0) or np.any(mesh.faces >= len(mesh.vertices)):
        raise ValueError('Mesh faces contain invalid vertex indices')


def load_mesh_bytes(raw, file_type):
    """Validate unprocessed bytes, then weld only exactly identical vertices.

    STL stores separate vertices for each triangle. Exact welding establishes
    shared edges without moving coordinates or discarding faces. Trimesh's
    default cleanup is disabled so nonfinite input cannot silently disappear.
    """
    if not isinstance(file_type, str) or file_type.lower() != 'stl':
        raise ValueError('Only STL input is supported; scene transforms are not interpreted')
    mesh = trimesh.load(io.BytesIO(raw), file_type='stl', force='mesh', process=False)
    _validate_mesh(mesh)
    vertices, inverse = np.unique(mesh.vertices, axis=0, return_inverse=True)
    return trimesh.Trimesh(vertices=vertices, faces=inverse[mesh.faces], process=False)


def mesh_audit(mesh):
    _validate_mesh(mesh)
    edges, count = np.unique(np.sort(mesh.edges, axis=1), axis=0, return_counts=True)
    return {
        'vertices': int(len(mesh.vertices)), 'triangles': int(len(mesh.faces)),
        'bounds_input_units': mesh.bounds.tolist(),
        'edge_watertight': bool(mesh.is_watertight),
        'winding_consistent': bool(mesh.is_winding_consistent),
        'boundary_edges': int(np.count_nonzero(count == 1)),
        'nonmanifold_edges': int(np.count_nonzero(count > 2)),
        'limits': 'Edge audit does not prove vertex manifoldness, absence of self-intersection, manufacturability or motion feasibility.'
    }


def section_material(mesh, z):
    """Even-odd fill of closed XY rings at finite z; reject invalid rings."""
    if not np.isfinite(z):
        raise ValueError('Finite section height required')
    _validate_mesh(mesh)
    if mesh.body_count != 1:
        raise ValueError('Section fill accepts one connected body only; split and qualify multiple solids explicitly')
    if not mesh.is_watertight or not mesh.is_winding_consistent:
        raise ValueError('Section fill requires edge-watertight, winding-consistent input')
    section = mesh.section(plane_origin=[0, 0, float(z)], plane_normal=[0, 0, 1])
    if section is None:
        return None
    if not section.is_closed:
        raise ValueError('Section includes open entities; cannot infer filled material')
    material = Polygon()
    polygons = []
    rings = section.discrete
    if not rings:
        return None
    for ring in rings:
        ring = np.asarray(ring, dtype=float)
        if ring.ndim != 2 or ring.shape[1] != 3 or not np.isfinite(ring).all():
            raise ValueError('Section rings must contain finite 3D points')
        if len(ring) < 4 or not np.allclose(ring[0], ring[-1], atol=1e-8, rtol=0):
            raise ValueError('Open or degenerate section ring; cannot infer filled material')
        p = Polygon(ring[:, :2])
        if not p.is_valid or p.area <= 0:
            raise ValueError('Invalid section polygon; no automatic repair is applied')
        for previous in polygons:
            if p.boundary.intersects(previous.boundary):
                raise ValueError('Crossing, duplicate or touching rings; ambiguous material fill')
            if p.intersects(previous) and not (p.contains(previous) or previous.contains(p)):
                raise ValueError('Overlapping rings without strict containment')
        polygons.append(p)
        material = material.symmetric_difference(p)
    if material.is_empty:
        return None
    if not material.is_valid:
        raise ValueError('Invalid section material')
    return material


def section_relation(a, b, z, area_tolerance=1e-8):
    if not np.isfinite(z) or not np.isfinite(area_tolerance) or area_tolerance < 0:
        raise ValueError('Finite z and nonnegative finite area tolerance required')
    pa, pb = section_material(a, z), section_material(b, z)
    if pa is None or pb is None:
        return {'z': float(z), 'area_tolerance': float(area_tolerance), 'status': 'no_shared_section',
                'overlap_area': None, 'separation': None}
    overlap = float(pa.intersection(pb).area)
    return {'z': float(z), 'area_tolerance': float(area_tolerance),
            'status': 'overlap' if overlap > area_tolerance else 'at_or_below_area_tolerance_at_sample',
            'overlap_area': overlap, 'separation': float(pa.distance(pb))}


def fit_circle_2d(points):
    """Least-squares vertex-circle fit; not a minimum bore clearance proof."""
    p = np.asarray(points, dtype=float)
    if p.ndim != 2 or p.shape[1] != 2 or len(p) < 3 or not np.isfinite(p).all():
        raise ValueError('At least three finite 2D points required')
    if np.linalg.matrix_rank(p - p.mean(axis=0)) < 2:
        raise ValueError('Collinear points do not define a circle')
    # Center coordinates first to avoid precision loss at large translations.
    origin = p.mean(axis=0); q = p-origin
    v, _, _, _ = np.linalg.lstsq(np.c_[2*q, np.ones(len(q))], (q*q).sum(axis=1), rcond=None)
    center = v[:2] + origin
    radii = np.linalg.norm(p-center,axis=1)
    return {'center': center.tolist(), 'mean_vertex_radius': float(radii.mean()),
            'max_radial_residual': float(np.abs(radii-radii.mean()).max()),
            'limits': 'Vertex radius is not polygon inradius or actual manufactured bore size.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('first', type=Path)
    parser.add_argument('--second', type=Path)
    parser.add_argument('--z', type=float, action='append', default=[])
    parser.add_argument('--area-tolerance', type=float, default=1e-8)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if bool(args.second) != bool(args.z):
        parser.error('--second and one or more --z must be supplied together')
    # Do not overwrite either source, including symlink aliases.
    if args.output.resolve() in {p.resolve() for p in [args.first,args.second] if p is not None}:
        parser.error('Output must not replace an input')
    paths=[args.first]+([args.second] if args.second else [])
    if args.output.exists() and any(args.output.samefile(p) for p in paths):
        parser.error('Output must not replace an input hardlink')
    meshes=[]; records=[]
    for path in paths:
        raw=path.read_bytes()
        # Audit exactly the bytes that were hashed; no second filesystem read.
        mesh=load_mesh_bytes(raw,file_type=path.suffix.lstrip('.'))
        meshes.append(mesh)
        records.append({'input_name':path.name,'sha256':hashlib.sha256(raw).hexdigest(),'audit':mesh_audit(mesh)})
    result={'scope':'finite static geometry only; assembly transforms supplied by caller',
            'units':'input units; STL has no standardized unit metadata',
            'mesh_processing':'automatic cleanup disabled; exactly identical vertices welded; no coordinates moved or faces removed',
            'inputs':records,'samples':[]}
    if len(meshes)==2:
        result['samples']=[section_relation(*meshes,z,args.area_tolerance) for z in args.z]
    payload = json.dumps(result,indent=2,allow_nan=False)+'\n'
    # Exclusive creation is the final guard, including links raced into place
    # after the earlier alias checks. Never truncate an existing destination.
    with args.output.open('x', encoding='utf-8', newline='\n') as output:
        output.write(payload)

if __name__=='__main__':main()
