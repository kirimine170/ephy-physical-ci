"""Validate binary STL topology using Python's standard library.

Vertex welding uses 1e-5 mm precision. This is not a triangle-pair
self-intersection test or a physical-fit test.
"""
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import struct

EXPECTED = {
    'esp32s3_sense_base.stl', 'esp32s3_sense_collar_PRINT_FLIPPED.stl',
    'nrf52840_sense_base.stl', 'nrf52840_sense_collar_PRINT_FLIPPED.stl',
    'ra4m1_base.stl', 'ra4m1_collar_PRINT_FLIPPED.stl',
    'tray_four_xiao.stl', 'OPTIONAL_single_slot_fit_coupon.stl',
}


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def inspect_stl(path):
    data = Path(path).read_bytes()
    if len(data) < 84:
        raise ValueError('Truncated STL header')
    count = struct.unpack_from('<I', data, 80)[0]
    if count == 0 or len(data) != 84 + 50*count:
        raise ValueError('Expected nonempty binary STL with exact size')
    edges, directed = Counter(), Counter()
    neighbors = defaultdict(set)
    points = set()
    volume, zero_area = 0.0, 0
    for values in struct.iter_unpack('<12fH', data[84:]):
        raw = [tuple(values[i:i+3]) for i in (3, 6, 9)]
        if not all(math.isfinite(v) for p in raw for v in p):
            raise ValueError('Nonfinite vertex')
        tri = [tuple(round(v, 5) for v in p) for p in raw]
        points.update(tri)
        ab = tuple(raw[1][i]-raw[0][i] for i in range(3))
        ac = tuple(raw[2][i]-raw[0][i] for i in range(3))
        zero_area += math.sqrt(sum(v*v for v in cross(ab, ac))) < 1e-9
        volume += sum(x*y for x, y in zip(raw[0], cross(raw[1], raw[2]))) / 6
        for a, b in zip(tri, tri[1:]+tri[:1]):
            edges[tuple(sorted((a, b)))] += 1
            directed[(a, b)] += 1
            neighbors[a].add(b)
            neighbors[b].add(a)
    remaining = set(points)
    components = 0
    while remaining:
        components += 1
        queue = [remaining.pop()]
        while queue:
            for neighbor in neighbors[queue.pop()]:
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    queue.append(neighbor)
    mins = [min(p[i] for p in points) for i in range(3)]
    maxs = [max(p[i] for p in points) for i in range(3)]
    result = {
        'triangles': count,
        'vertices_welded_1e5_mm': len(points),
        'boundary_edges': sum(n == 1 for n in edges.values()),
        'nonmanifold_edges': sum(n != 2 for n in edges.values()),
        'inconsistent_oriented_edges': sum(
            directed[(a, b)] != 1 or directed[(b, a)] != 1 for a, b in edges),
        'zero_area_triangles': zero_area,
        'connected_components': components,
        'signed_volume_mm3': volume,
        'bbox_mm': [round(b-a, 5) for a, b in zip(mins, maxs)],
        'z_min_mm': mins[2],
        'watertight': all(n == 2 for n in edges.values()),
    }
    if (not result['watertight'] or result['inconsistent_oriented_edges']
            or zero_area or volume <= 0 or components != 1 or abs(mins[2]) > 1e-5):
        raise ValueError(f'Invalid printable STL {Path(path).name}: {result}')
    return result


def validate(root):
    files = {p.name: p for p in (root/'stl').glob('*.stl')}
    if set(files) != EXPECTED:
        raise ValueError('Expected exactly the eight documented STL variants')
    return {name: inspect_stl(files[name]) for name in sorted(files)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    root = parser.parse_args().root
    report = validate(root)
    (root/'reports').mkdir(exist_ok=True)
    (root/'reports'/'mesh_validation.json').write_text(
        json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
