# Axial cylindrical tool screen v1

`screen-tool` screens a nominal flat-end cylindrical tool translating along its
fixed axis against one frozen valid single-solid STEP obstacle. This stage
constructs the swept solid analytically. The existing `check-path` stage retains
its discrete pose sampling and its different outcome semantics.

```sh
physical-ci screen-tool tool.json --output results/tool-001.json
```

Only the existing CadQuery/OCCT geometry extra is used. No dependency or license
is added, and no software is downloaded or installed automatically.

## Strict input

```json
{
  "schema_version": 1,
  "units": "mm",
  "frame": "assembly",
  "obstacle": {
    "path": "obstacle.step",
    "sha256": "<lowercase SHA256 of the exact frozen STEP bytes>",
    "frame": "assembly"
  },
  "tool": {
    "kind": "flat_end_cylinder",
    "radius_mm": 2,
    "length_mm": 2,
    "tip_mm": [0, 0, -1],
    "axis": [0, 0, 1],
    "travel_mm": 6
  },
  "numeric_epsilon_mm": 0.0000001,
  "numeric_epsilon_mm3": 0.000000001
}
```

The digest placeholder must be replaced. All listed fields are required;
unknown fields are rejected at every object level. Version is integer 1, not a
boolean or float. Coordinates and dimensions must be finite nonboolean numbers.
Radius and cylinder length are strictly positive; travel is nonnegative. Zero
travel still checks the entire initial cylinder. Numeric epsilons are strictly
positive and are numerical decision thresholds, not manufacturing tolerances.

The declared axis must have norm within `1e-12` of 1. It is normalized to unit
length for all geometry calculations; both declared and used axes are recorded.
This dimensionless check is separate from the distance epsilon. Non-unit axes
are rejected rather than interpreted as extra travel or scale.

Both obstacle and tool share explicit `assembly` coordinates and `mm` units.
No coordinate transform, rotation, lateral movement, or waypoint list is
accepted. The caller is responsible for the STEP's actual units and placement.
The relative POSIX `.step`/`.stp` path must stay inside the specification
directory, including after symlink resolution. Absolute/parent/Windows
drive/stream paths, wrong frames, and malformed SHA256 are rejected.

Input JSON is limited to 64 KiB and STEP to 64 MiB. Duplicate JSON keys,
malformed JSON, NaN/infinity, overflow, underflow of nonzero JSON numbers to
zero, nonfinite derived geometry, and numerically collapsed sweep extents/travel
are rejected. No geometry generator is
imported by the checker. The real kernel must accept exactly one valid positive-
volume solid, with finite bounds; multiple solids and loose extra geometry are
rejected. STEP import failure is an input failure.

## Frozen-byte binding and outputs

The stage reads the STEP once into bounded bytes, checks their SHA256 against
the specification, writes those bytes to a private temporary `.step` snapshot,
and imports that snapshot. The shared hash helper verifies the snapshot before
import and again before returning the report. The snapshot is then deleted.
The report's STEP hash therefore describes exactly the frozen input used for
analysis. Later changes to the live source do not change the imported geometry
or imply that the report describes those new live bytes.

The specification hash also comes from the bytes actually parsed. Reports omit
timestamps and local paths. The existing exclusive-output and finite-JSON
serialization guards reject existing outputs and aliases to either input.
No report is written after an input/hash/snapshot validation failure.

## Sweep and decision

For radius `r`, cylinder length `L`, initial tip `p`, used unit axis `d`, and
travel `s`, the initial cylinder runs from `p-Ld` to `p`. Its swept volume for
the permitted motion is one cylinder of radius `r` and length `L+s`, from
`p-Ld` to `p+sd`. Both flat end caps and every intermediate translated pose are
included. A clear centerline or two clear endpoint poses alone is insufficient.

The kernel measures common volume `V` in mm3 and minimum solid-to-solid distance
`D` in mm. Let `eD` and `eV` be the explicit distance and volume epsilons.

| Measurement | Outcome |
| --- | --- |
| `V == 0`, finite `D > eD` | `model_clear` |
| `V > eV`, finite `0 <= D <= eD` | `interference` |
| `0 < V <= eV` | `indeterminate` |
| `V == 0`, `0 <= D <= eD` (including contact) | `indeterminate` |
| Positive volume with `D > eD` | `indeterminate` (kernel contradiction) |
| Invalid/nonfinite/negative measurements, invalid Boolean shape, or kernel operation failure | `indeterminate` |

Invalid sweep construction or disagreement with analytic cylinder volume is
also `indeterminate`. The analytic volume identity uses its own small relative
numerical check; a large user overlap epsilon cannot mask an incorrect swept
solid. Unavailable measurements are `null` in finite JSON, with reasons; they
never become a model-clear result. The report includes the obstacle hash/volume,
tool and sweep geometry, both measured quantities, backend version, epsilons,
outcome, and reason codes.

Exit code 0 means a report was produced, including `interference` or
`indeterminate`. It is not a physical pass. Existing input/execution failure
codes 2/1 apply to rejected inputs and missing backend or file failures.

`full_tool_assembly_verified`, `grip_access_verified`, `physical_safety_verified`,
and `printer_ready` are always false. `support_breakage` and `support_removal`
are `not_implemented`; `physical_validation` is `not_performed`. This nominal
cylinder model does not include an actual complete tool, flutes, taper, holder,
gripping fixtures, force, support fracture, removal access, or material behavior.
No physical safety or manufacturable clearance is guaranteed. Rotation, lateral
motion, and path search remain outside this stage.

## Original synthetic oracles

```sh
python -m unittest discover -s tools/mechanical-ci/tests -p test_tool.py -v
python -m unittest discover -s tools/mechanical-ci/tests -v
python scripts/validate_repository.py --check-sensitive-patterns
```

The real-kernel tests generate simple original obstacles, export frozen STEP,
and run the independent frozen-byte stage. A 2 mm radius tool through a 2.5 mm
radius bore has a 0.5 mm gap. A 1.5 mm bore obstructs that tool despite a clear
centerline; with obstacle thickness 3 mm the overlap oracle is
`pi * (2^2 - 1.5^2) * 3`. An equal-radius bore touches and is indeterminate.
Further oracles cover a thin middle wall with clear endpoint tools, complete
sweep containment, zero travel, and invariance under a shared rigid transform.
Real malformed/multi-solid STEP rejection and CLI hash round-trip are included.

Schema/IO tests use explicitly labeled mocks only. They verify strict JSON,
finite arithmetic, byte identity, snapshot tampering, live-source mutation,
output protection, determinism, conservative metric decisions, and kernel
failure handling. They are not geometry validation. Nine real-kernel tests are
skipped if the existing CadQuery/OCCT extra is unavailable; execute them on the
existing geometry CI or an already provisioned environment. A skip is an
unperformed check, and kernel results are not claimed by the Windows mock tests.
