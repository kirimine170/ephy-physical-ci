# ADR 0001: Safe host-configuration boundaries

## Status

Accepted．

## Context

The first managed node already has working key-only SSH，a restrictive UFW policy，and an installer-created administrator account．A single convergent playbook that changes access and application state would create an avoidable lockout risk．The public repository also cannot contain real host addresses，keys，password hashes，or USB serial numbers．

## Decision

- `site.yml` manages only packages，new least-privilege accounts，directories，minimal udev access，and optional service files．
- SSH and UFW use separate opt-in playbooks with explicit approval variables．
- The existing `hil` account is not managed during the first apply．
- `/dev/serial/by-id` remains the stable device identity; udev adds permissions only．
- Real inventory is ignored and external to normal Git history．
- The agent service and MCU toolchain installation are disabled by default．

## Consequences

Fresh-host restoration is a staged procedure rather than one command．This costs an additional verification step but keeps a working recovery session and makes privilege changes reviewable．
