# Synthetic support-screen end-to-end verification

This is a research test harness for public source commit
`e45770fb168b6ba64ee41922ec70adab76eddb55` of `kirimine170/ephy-physical-ci`.
It does not modify that source, install software, contact a printer, or use product CAD.

## Reproduce

Prerequisites: Python 3.12, CadQuery 2.7.0, and an existing PrusaSlicer 2.9.2 CLI.
Use an ordinary Python invocation; assertions must be enabled.
Set any required runtime library search path in the invoking environment.
Use a checkout at the stated commit as SOURCE and a new output directory:

```sh
python run_e2e.py --source-root SOURCE --slicer /path/to/prusa-slicer --output NEW_OUTPUT
python reproduce_hash_window.py --source-root SOURCE --fixture NEW_OUTPUT/a_auto --output NEW_CONTROL
```

The independent Decimal auditor does not import the product parser or clipper.
Geometry, profile, ROIs, and pose gates are written before the first slice.
The three cases are support auto, support off, and support auto translated by
(20, 10) mm. Positive evidence is a source-line endpoint or midpoint strictly
inside a predeclared ROI. The actual screen must flag that same line and ROI.
External-perimeter landmarks independently test orientation and placement.
Neither ROIs nor tolerances are adjusted to fit generated support paths.

## Results and limits

Final results are `run-003/summary.json`, `run-003/provenance.json`, and
`run-003/preregistered-plan.json`. The complete local run also holds frozen
synthetic inputs, raw G-code, ROI files, per-case reports, and repeat reports.
Raw local slicer logs may contain absolute paths and should not be published.
Publication candidates are the two scripts, this README, and compact JSON only.

The initial run-001 was rejected by PrusaSlicer before slicing because relative
extrusion requires `layer_gcode = G92 E0`. That single explicit profile setting
was added before the fresh run-002. No ROI or geometric oracle was changed.
The run-002 source export contained an extra trailing blank line per file;
before run-003, all 12 exported source/profile/test files were replaced with
exact GitHub bytes and individually verified against Git blob SHA values.

Input hashes are compared before and after each ordinary screen sequence.
Equality is an observation at those two times, not proof against temporary
changes and restoration. The separate deterministic hash-window control
mutates synthetic copies after input validation and before screening returns.
It demonstrates that current reports bind the earlier read bytes but do not
prove that source paths remain unchanged through report creation.

The source's focused support test module is run separately. A full repository
validation is not claimed from this partial source export; run the repository
validator in the complete publishing checkout before integration.

This is numerical/CLI integration evidence only. No physical printing,
support removal, bead metrology, force, retention, or manufacturing validation
was performed. The pre-existing extreme-E underflow P2 remains unresolved.
There are no claims of identical G-code bytes across separate slicer runs.
