# Architecture

## Purpose

This document describes the stable responsibility boundaries of the Physical CI infrastructure．

## Repository layers

- `.ephy/` contains the machine-readable project identity，direct repository relationships，and data policy．
- `docs/` contains architecture，relationship，security，and decision records．
- `.github/` contains repository-local collaboration and validation configuration．
- `inventories/example/` contains non-routable configuration examples．
- `inventories/sanitized/` records non-secret observed host capabilities．
- `inventories/local/` is Git-ignored and holds addresses，keys，and full USB serials．
- `playbooks/` separates non-disruptive configuration from SSH and firewall changes．
- `roles/` owns accounts，directories，USB policy，and optional service deployment．
- `manifests/` defines the version and checksum boundary for future MCU tools．
- `scripts/` contains repository and infrastructure validation．
- `tests/` verifies safety boundaries without contacting a Physical CI host．

## Responsibility boundaries

Each Ephy repository owns a defined project responsibility．Cross-repository relationships must be explicit in `.ephy/project.yaml`，but downstream consumers are discovered centrally by the future `ephy` meta repository rather than copied into every repository．Git submodules are not an architecture model for Ephy relationships．

The default `playbooks/site.yml` must not manage SSH，UFW，or the installer-created legacy account．Those operations have separate playbooks，explicit approval variables，and independent access verification requirements．The current service role carries a hardened unit template but does not install or enable it unless both deployment variables and a real agent command are supplied．

USB access rules set only group ownership and mode for the known VID/PID pairs．They do not create alternate device symlinks．Job implementations must use `/dev/serial/by-id` from ignored local inventory and may use `/dev/serial/by-path` as a physical-port assertion．

## Implementation state and proposals

Document current behavior as implementation state．Document unaccepted ideas as proposals，and use an ADR when a decision has lasting architectural impact．Do not infer delivery dates or completion percentages from the project status field．
