# Physical CI boundary

## Current state

This repository is in design status．It defines how Ephy requests physical-device build，flash，test，and result collection through `ephy-worker`．It does not yet contain device drivers，board-specific flashing implementations，or a production scheduler．

## Responsibilities

- Describe a versioned job request for build，flash，test，capture，and cleanup phases．
- Identify hardware by non-secret inventory ID and declared capabilities．
- Isolate concurrent jobs and always attempt safe cleanup after failure or cancellation．
- Return structured results，tool versions，artifact hashes，and redacted logs．
- Keep board credentials and signing keys outside Git and outside job payloads．

## Boundaries

`ephy-worker` owns authorized remote execution．`ephy-runtime` is an integration peer that submits or interprets jobs．This repository owns physical-device orchestration contracts，not general worker transport or runtime policy．It never receives `ephy-private` as a repository and stores no camera master images．
