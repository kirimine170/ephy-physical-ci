# Support ROI screen v1

`screen-support` is implemented for nominal, planar, single-extruder linear
G-code and explicitly located protected AABBs. It uses the existing G-code
extractor, SHA256 helper, and fresh-output safeguards. It adds no dependency
or license. All test inputs are original synthetic data.

```sh
physical-ci screen-support nominal.gcode --roi protected.json --output screen-001.json
```

The only accepted ROI frame is `gcode_machine_coordinates`, with units `mm`.
Assembly and print frames, transformation matrices, and unknown fields are
rejected. An assembly-to-G-code transformation has not been validated.

## Strict input contract

```json
{
  "schema_version": 1,
  "frame": "gcode_machine_coordinates",
  "units": "mm",
  "gcode_sha256": "<replace with the lowercase SHA256 of the exact G-code bytes>",
  "regions": [
    {
      "id": "protected-cavity",
      "min_mm": [0, 0, 0],
      "max_mm": [1, 1, 1]
    }
  ]
}
```

The digest placeholder above must be replaced; it is not a valid digest.
For example, `sha256sum nominal.gcode` provides the digest on Linux.
The ROI must use UTF-8 JSON. Version 1 is an integer, not a boolean or float.
Every region has exactly `id`, `min_mm`, and `max_mm`. IDs must be unique,
nonblank strings of at most 200 characters. Bounds are triples of finite
nonboolean numbers, with `min_mm < max_mm` on every axis.

Unknown or missing fields, duplicate JSON keys at any depth (including escaped
spellings of the same key), NaN/infinity, numeric overflow, malformed JSON,
invalid bounds, and hash mismatches are rejected. Empty region lists are
rejected. Limits are 1 MiB of ROI bytes, 1,000 regions, 64 MiB of G-code, and
1,000,000 eligible-support-event/ROI intersection checks. Overflow in envelope
or clip arithmetic also fails the stage. Both input hashes are recorded in the
report, and changed inputs are detected before writing it.

Existing outputs, output aliases to either input, hardlinks, and symlinks are
rejected. Output is created exclusively. The report is serialized to finite JSON
before opening the output file. Identical input bytes produce identical reports
at different fresh output paths; timestamps and local paths are omitted.

## Proxy and clip interval

The proxy is named `axis_aligned_envelope_proxy`. For each eligible support or
interface path with width `w` and height `h`, expand the protected AABB by
`(w/2, w/2, h)` on both its lower and upper sides. Apply a closed slab clip to
the line segment against that expanded box. Contact at a face, edge, or corner
counts as a candidate. Overlap of the path's bounding box alone is insufficient.

`clip_interval = [t_enter, t_exit]` uses
`p(t) = from_mm + t * (to_mm - from_mm)`, with `0 <= t <= 1`.
Endpoints are the deposited portion returned by the extractor, after recovery
of retract debt. Reversing a path changes its interval accordingly. Boundary
ties affected by floating-point roundoff are resolved using exact rational
decimal representations of the parsed numbers; no geometric tolerance is added.

For ROI `[0,0,0]` to `[1,1,1]`, path `(-1,.5,.5)` to `(2,.5,.5)`,
`w=.4`, and `h=.2`, the oracle is `[.8/3, 2.2/3]`. A parallel path at
`y=1.2` or `z=1.2` touches; `1.21` misses. This height expansion is deliberately
symmetric `Z +/- h`, not a reconstructed layer volume.

A fully located stationary support prime with known dimensions uses the same
proxy around its point. Its interval is `[0,1]`, and its `kind` is
`stationary_prime`. This is a nominal point-envelope screen; the amount and
shape of deposited prime material are not reconstructed. Any positive
deposition is retained, including very small positive E and nonzero motion.
Pure retract recovery is excluded.

## Observation and coverage

`observed_hits` is a list of candidates. Each contains G-code `line`, exact
`role`, `roi_id`, `kind`, `clip_interval`, nominal endpoints, width, and height.
The report also contains the normalized ROIs. Hits are ordered by line and ROI
ID. `coverage_complete` separately describes whether every extracted deposition
event could be classified within this bounded screen.

| Event | Treatment |
| --- | --- |
| Planar `Support material` or `Support material interface`, with dimensions | Screen against every ROI |
| Known non-support role, with dimensions and planar path | Exclude from support candidates |
| Unknown or missing role | Coverage gap; do not guess support classification |
| Missing width or height | Coverage gap; do not substitute nozzle defaults |
| Any nonplanar deposition | Coverage gap; skip that event's geometry |
| Stationary prime with unknown position, role, or dimensions | Coverage gap |
| Fully known support prime | Screen point envelope |
| Fully known non-support prime | Exclude from support candidates |

The exact recognized non-support labels are `Perimeter`, `External perimeter`,
`Overhang perimeter`, `Internal infill`, `Solid infill`, `Top solid infill`,
`Bridge infill`, `Internal bridge infill`, `Gap fill`, `Skirt/Brim`, `Skirt`,
`Brim`, `Ironing`, and `Wipe tower`. All other labels, including `Custom`, empty
TYPE, and new slicer roles, leave coverage incomplete. Ordinary comments are
ignored; unknown dimension metadata is not interpreted as width or height.
Recognized TYPE/WIDTH/HEIGHT/Z metadata requires standalone uppercase comment
lines, with leading whitespace allowed. Ambiguous inline or case variants are
rejected instead of reusing a stale role or dimension.

`coverage_gaps` records line, role, event kind, and reasons. Gaps apply even to
events outside the ROIs or known non-support deposition with missing dimensions
or nonplanar motion. A hit may coexist with incomplete coverage.

| Condition | `outcome` |
| --- | --- |
| At least one hit, with either coverage state | `candidate_found` |
| No hits and complete bounded coverage | `no_candidate_observed` |
| No hits and incomplete coverage | `unknown` |

Exit code 0 means that the stage produced a report, including `unknown` or
`candidate_found`. It does not assert a physical pass. Exit codes 1 and 2 retain
the existing execution/input failure meanings. A caller must inspect both
`observed_hits` and `coverage_complete`; a negative report with gaps is unknown.

The report always states `support_removal=not_implemented`,
`physical_validation=not_performed`, `printer_ready=false`, and
`assembly_to_gcode_transform_verified=false`. This screens nominal paths,
not real beads. It guarantees neither actual deposited material nor sagging,
removal access, post-removal function, bonding, or strength. Complete coverage
is limited to the accepted dialect, supplied metadata, and explicit machine-frame
ROIs; it is not an assertion about all protected product regions.

## Synthetic verification

```sh
python -m unittest discover -s tools/mechanical-ci/tests -v
python scripts/validate_repository.py --check-sensitive-patterns
```

Tests include the analytic oracle, both endpoints outside, parallel and corner
contact, near-contact separation, reversed paths, diagonal bounding-box false
positives, support/interface versus perimeter, unknown metadata and roles,
nonplanar deposition, stationary primes, tiny extrusion/motion, arithmetic
overflow, strict JSON, hash tampering, resource limits, output protection, and
byte determinism. Geometry-extra and real pinned slicer integration checks
remain conditional as described in the CLI README; skipped checks are not
successful integration runs.
