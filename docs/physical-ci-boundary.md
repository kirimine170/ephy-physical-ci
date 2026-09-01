# Physical CI boundary

## Current state

This repository defines how Ephy prepares a Physical CI host and invokes
reviewed device-reference entry points directly on that host．It contains no
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

Remote Physical CI execution does not pass through `ephy-worker`．A dedicated
Physical CI control plane authorizes and dispatches jobs directly to this host．
`ephy-runtime` is an integration peer that may submit or interpret future jobs．
This repository never receives `ephy-private` and stores no camera master
images．
