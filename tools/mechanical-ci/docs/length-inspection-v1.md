# Measured length inspection v1

`inspect-length` matches one human-entered length record to one independent
requirement, then reports execution status, judgment, reason, and evidence class.
It implements the supplied bounded MVP scope (REQ-02, DATA-01, POST-01, DIM-01,
QA-03). The reference files `ephy_manufacturing_inspection_research_v0.1.md` and
`ephy_inspection_catalog_v0.1.json` were not present in the repository or task
inputs; this checkout has no `.agents/skills`. No catalog entries, acceptance
thresholds, or definitions beyond the supplied specification are inferred.

## Run the synthetic examples

From `tools/mechanical-ci`, use Python 3.10+ and the existing CLI installation:

```sh
python -m pip install -e .
physical-ci inspect-length examples/synthetic/length-inspection/subject.json \
  --requirement examples/synthetic/length-inspection/requirement.json \
  --measurement examples/synthetic/length-inspection/pass.json \
  --output results/length-pass-001.json
```

Substitute `fail.json` or `indeterminate.json` and a **fresh** output filename
to run the other examples. They produce respectively:

```json
{"execution_status":"complete","judgment":"pass","reason":"interval_within_closed_bounds","evidence_class":"record","synthetic":true}
{"execution_status":"complete","judgment":"fail","reason":"interval_disjoint_from_closed_bounds","evidence_class":"record","synthetic":true}
{"execution_status":"complete","judgment":"indeterminate","reason":"uncertainty_unevaluated","evidence_class":"record","synthetic":true}
```

These are excerpts of the full stdout/output-file reports. Stderr explains the
judgment, value, closed bounds, policy, and uncertainty status in human terms.
All examples and their observation record are synthetic. The illustrative
9.9–10.1 mm bounds are neither a product specification nor a recommended
tolerance. No real part was printed or measured to generate these examples.

## Three independent inputs

The subject JSON selects the expected physical sample and jobs independently
of the candidate record:

```json
{
  "schema_version": 1,
  "sample_id": "synthetic-coupon-001",
  "design_job_ref": "synthetic-design-001",
  "manufacturing_job_ref": "synthetic-print-001"
}
```

The requirement JSON is maintained independently of the candidate measurement:

```json
{
  "schema_version": 1,
  "feature_id": "length-A",
  "requirement_revision": "r1",
  "unit": "mm",
  "process_state": "after_support_removal",
  "measurement_method": "caliper_length",
  "tolerance": {"lower": 9.9, "upper": 10.1},
  "judgment_policy": {
    "name": "interval_containment_v1",
    "unevaluated_uncertainty": "indeterminate"
  }
}
```

The checked-in `pass.json` is a complete measurement input. Its required fields
are `schema_version`, all three subject bindings, all five requirement bindings
(`feature_id`, `requirement_revision`, `unit`, `process_state`, and
`measurement_method`), `value`, `source_kind`, `uncertainty`, and `evidence_refs`.
Use `source_kind: "human_measurement"` for a human observation and `"synthetic"`
for fabricated test data. Uncertainty must have exactly one form:

```json
{"status":"evaluated","value":0.01,"unit":"mm","basis":"documented evaluation of the interval half-width"}
{"status":"unevaluated","reason":"uncertainty has not been evaluated"}
```

There is no default uncertainty, policy, process state, unit, revision, or
method. Explicit evaluated zero is allowed; unknown never becomes zero.
Strings must be nonblank with no outer whitespace. Binding strings are matched
exactly; no case folding or approximate identity match is performed. Job refs
are identifiers, not an integration that fetches design/manufacturing systems.

Every evidence ref contains `path` and lowercase `sha256` of an existing,
nonempty local file. The path must be relative POSIX, stay inside the measurement
directory after resolution, and contain no parent, backslash, drive, or stream
syntax. Up to 16 refs and 64 MiB per file are supported. Evidence hashes are
checked against the exact bounded bytes read; missing/empty evidence cannot
pass. A wrong hash is an input error. No evidence is executed or transmitted.
The operator must ensure the record and referenced bytes actually describe the
selected sample; hashes establish byte provenance, not measurement authenticity.

## Explicit decision policies

Let `x` be the measured length and `[L, H]` the inclusive tolerance interval.
Both policies are project-defined mathematical rules, not normative metrology
standards or a certification claim:

- `simple_acceptance_v1`: pass iff `L <= x <= H`; otherwise fail. Evaluated
  uncertainty does not alter this point rule. For unevaluated uncertainty,
  `unevaluated_uncertainty` must explicitly be `indeterminate` or `ignore`.
  The latter applies the point rule despite unknown uncertainty, retaining the
  unknown status and reason in the report.
- `interval_containment_v1`: the supplied evaluated uncertainty `u` is a
  nonnegative half-width of `[x-u, x+u]`. Pass iff that whole interval lies
  inside `[L,H]`. Fail iff it is strictly disjoint (`x+u < L` or `x-u > H`).
  Otherwise indeterminate, including an outside interval that merely touches a
  tolerance boundary. Unevaluated uncertainty always yields indeterminate;
  only `unevaluated_uncertainty: "indeterminate"` is supported here.

The `basis` documents the operator's evaluation; this MVP does not derive
uncertainty, a coverage factor, or a probability. No guardband is invented.
Nonnegative lengths, tolerance bounds, and uncertainty values must be finite
JSON numbers. Only `mm` is implemented; other units are rejected, never silently
converted. Decimal tokens are compared as exact rational numbers, so decimal
boundary contact uses no binary float epsilon. Numbers are limited to 128
characters, decimal exponents within ±100, and nonzero magnitudes from 1e-100
through values with decimal order 100. Reports encode quantities as decimal
strings to preserve precision. These are numerical/resource limits, not altered
acceptance criteria. Equal lower/upper bounds are allowed.

Each JSON is limited to 64 KiB; unknown/missing fields, duplicate keys, corrupt
JSON, invalid UTF-8, boolean numbers, NaN/infinity, unsupported exponents, and
inconsistent bindings are rejected. The CLI never edits a requirement or
loosens its tolerance to accommodate a candidate. Reports include the independent
requirement and SHA256 of the exact parsed input bytes.

## Report and exit meanings

Successful report schema is version 1 for `command: "inspect-length"`:

| Situation | Execution status | Judgment / reason | Exit |
| --- | --- | --- | --- |
| Valid comparison | `complete` | `pass`, `fail`, or `indeterminate` with policy reason | 0 |
| Omit `--requirement` or `--measurement` | `not_run` | `indeterminate` / `missing_requirement` or `missing_measurement` | 0 |
| Empty refs or missing/empty evidence file | `not_run` | `indeterminate` / `missing_evidence` | 0 |
| Unknown uncertainty under an indeterminate policy | `complete` | `indeterminate` / `uncertainty_unevaluated` | 0 |
| Wrong sample/job/feature/revision/process/method binding | `error` | `not_applicable` / `binding_mismatch` | 2 |
| Other malformed/unsupported input, wrong evidence hash, existing output | `error` | `not_applicable` / `invalid_input` | 2 |
| File I/O failure, including missing explicitly requested JSON | `error` | `not_applicable` / `execution_error` | 1 |

Validation errors emit a structured JSON report on stdout and explanation on
stderr, with **no output file**, consistent with existing CLI failure behavior.
All generated files use exclusive creation and protect inputs/evidence.
Exit 0 means the requested stage reported successfully; consumers must read
`judgment`. A physical fail does not mean the CLI failed. Existing exit 3 remains
reserved for the older `check-path` regression-expectation mismatch.

Evidence class is `measurement` for declared human measurement records, and
`record` for synthetic or missing measurement data. No static CAD or prediction
is promoted to measurement evidence. This command consumes human observations;
the software performs no physical measurement, so its own
`physical_validation` remains `not_performed`. Scope is one declared length of
one sample, not whole-part acceptance. `printer_ready` stays false. Unimplemented
support-removal and physical-safety gates are reported as `not_implemented`.
Existing CLI commands and their result schemas are unchanged.

## Next independent candidates

The next minimal item is one genuine human-recorded length with an independently
approved requirement revision, documented uncertainty policy, and sample-bound
evidence. Validate that record through this same command without changing the
requirement to fit the result.

Separate future candidates, each requiring its own specification and evidence:

- A fixed-profile planned deposited-region check including support and brim;
  this would not establish printhead clearance.
- Survival of one wall or hole in slicer output after validated coordinate
  mapping; no general topology or whole-design guarantee.
- Support-removal observations for one coupon and tool, without invented forces.

No robot control, G-code transmission, printing, large CAD framework, nonlinear
or full thermal FEM, certification, or safety guarantee is added.
