# Finite-section geometry experiment

Original reusable helpers for mesh edge audits，filled XY sections at declared
finite heights，pairwise section area/distance，and least-squares circle fits．
This repository includes the module and synthetic regressions as a standalone
research experiment．It is not a `physical-ci` CLI command or a physical
acceptance gate．

The existing CLI checks frozen STEP translations and tool sweeps，and screens
G-code support against AABBs．This experiment adds mesh section analysis without
replacing those checks．See [the methods and findings](ENGINEERING_FINDINGS.md)
for the analysis procedure and limits．

## Public inputs and provenance

The experiment contains no third-party STL/ZIP files，source-derived outlines，
private geometry coordinates，credentials，personal data，or host paths．Tests
construct original boxes，circles，and an annulus at runtime．No private model is
needed to run them．

`candidate-manifest.json` preserves the original candidate bundle's SHA-256
records and authoring status．Its hashes describe the candidate before repository
adaptation，so changed repository files are indexed separately by the parent
[`manifest.json`](../manifest.json)．`test-results.txt` is the unchanged receipt
of fifteen tests in the authoring environment．It is historical evidence，not
the result of repository CI or the current commit's tests．

The integrated source differs from the candidate．A malformed-STL regression
found that Trimesh's default cleanup could discard a triangle containing NaN
and leave an apparently healthy box．The loader now disables cleanup，checks
unprocessed mesh coordinates and face indices，then welds only exactly identical
vertices．It moves no coordinates and removes no faces．The JSON report records
this policy in `mesh_processing`．Direct section helpers also reject nonfinite
heights and malformed/nonfinite rings．

## Run

Use Python 3.12 in an isolated environment with the experiment
dependencies．NumPy follows a major-version range；the other dependencies are
pinned．SciPy is included for Trimesh section operations．From this directory:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

On Windows，activate `.venv/Scripts/Activate.ps1` instead．The tests require no
external solver，slicer，printer，or network service．

The audit command reads caller-owned mesh files and writes a JSON report:

```sh
python section_geometry.py part_a.stl --output audit.json
python section_geometry.py part_a.stl --second part_b.stl \
  --z 2 --z 3 --output sections.json
```

STL does not declare standardized unit metadata．Use one known input unit and
define assembly transforms before calling the helper．The heights，distance，
and circle radius use that input unit；area uses its square．A missing section
produces `no_shared_section` with null overlap and separation．It does not mean
clearance or a passing result．Zero separation and zero overlap area can mean
touching；a positive clearance requires a positive measured separation．The
area tolerance is a numerical detection threshold，not a manufacturing tolerance．
Each sample records `area_tolerance` in squared input units．`overlap` means
the measured overlap exceeds that threshold；`at_or_below_area_tolerance_at_sample`
can still include positive overlap and contact．Read the reported area and
separation together；the threshold-relative status is not a clearance judgment．

## Checks and limits

Filled sections require one connected，edge-watertight，winding-consistent body
and valid closed rings．Open，degenerate，self-intersecting，crossing，touching，
and duplicate rings are rejected rather than repaired into an ambiguous fill．
Separate nested solids are rejected to avoid interpreting an independent solid
as a cavity．Legitimate cavities represented by multiple disconnected shells
are also outside this limited implementation．An edge audit can still report
those inputs without judging a filled section．

Regression coverage includes separated/overlapping/touching boxes，missing
sections，invalid finite parameters，circle fits，collinear rejection，large
translations，central-hole preservation，invalid/open mesh rejection，ambiguous
rings，raw malformed STL bytes，exact-coordinate welding，and output protection．
Additional direct contour controls use a valid single-body mesh so rejection
by the body-count guard cannot hide a missing ring check．CI explicitly
discovers this experiment's nested
test directory．Current test and CI outcomes must be assessed for the reviewed
commit；the preserved authoring receipt does not establish them．

Finite static 2D section samples do not reconstruct an assembly，prove
continuous 3D collision freedom，solve contact/friction/forces，predict dynamics
or FEM response，or qualify a manufactured part．Mesh edge watertightness alone
does not prove full manifoldness or freedom from self-intersections．Vertex
circle fits do not measure polygon inradius or manufactured bore clearance．

The original source has no selected license．Dependency licenses remain
unchanged．
