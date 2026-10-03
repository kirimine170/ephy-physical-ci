# Physical CI boundary

## Current state

This repository defines how Ephy prepares a Physical CI host and invokes
reviewed device-reference entry points through `ephy-worker`．It contains no
camera driver，board-specific firmware，or production scheduler．

## Responsibilities

- Reproduce the Ubuntu host through Ansible．
- Identify hardware by non-secret inventory ID and declared capability．
- Invoke build，flash，capture，and cleanup phases using explicit arguments．
- Validate structured results，tool versions，artifact hashes，and redacted logs．
- Isolate concurrent jobs and attempt safe cleanup after failure or cancellation．
- Keep credentials，signing keys，host addresses，and complete USB identities
  outside Git．

## Cross-repository contract

`ephy-cam` owns camera reference firmware and its host protocol adapter．The
generic `scripts/run-camera-reference` wrapper accepts that reference root at
runtime．`scripts/validate-camera-artifacts` validates only the resulting JPEG
and contract documents，so it does not need camera pins or sensor knowledge．

## Boundaries

`ephy-worker` owns authorized remote execution．`ephy-runtime` is an integration
peer that may submit or interpret future jobs．This repository never receives
`ephy-private` and stores no camera master images．

## Passive mechanical fixtures

`hardware/xiao-first-fit-v0.1/` contains original passive tabletop holders and
a four-board tray for unpowered fit checks．These are review-stage mechanical
fixtures，not device firmware or powered thermal-qualified enclosures．They do
not change USB access，host configuration，or the camera ownership boundary．

## Headless mechanical checks

`tools/mechanical-ci/` is a separate，bounded CLI prototype．It reads frozen
single-solid STEP files，samples a declared translation path，and can invoke a
local pinned PrusaSlicer to extract linear extrusion paths．Its included CAD
fixtures are newly generated synthetic regression inputs．

It does not connect to a printer or robot．Continuous collision，six-degree-of-
freedom search，support removal，contact/strength FEM，material calibration，and
robot measurement remain explicitly unimplemented gates．A passed regression
is not a physical-retention or manufacturing qualification．
