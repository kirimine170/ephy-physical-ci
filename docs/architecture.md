# Architecture

## Purpose

This document defines the stable responsibility boundaries of the Physical CI
infrastructure．

## Repository layers

- `.ephy/` contains project identity，relationships，and data policy．
- `inventories/example/` contains non-routable examples．
- `inventories/sanitized/` records non-secret observed capabilities．
- `inventories/local/` is Git-ignored and holds addresses，keys，and complete
  USB identities．
- `playbooks/` separates non-disruptive configuration from SSH and firewall
  changes．
- `roles/` owns accounts，directories，USB policy，validation packages，and the
  optional service boundary．
- `manifests/` defines the version/checksum boundary for future MCU tools．
- `scripts/` owns generic invocation and validation，not device firmware．
- `tests/` verifies safety boundaries without contacting a host．

## Host-change boundary

The default `playbooks/site.yml` must not manage SSH，UFW，or the legacy `hil`
account．Those operations have separate playbooks，explicit approval variables，
and independent access-verification requirements．The service role does not
install or enable a unit unless deployment variables and a real agent command
are supplied．

`playbooks/camera-validation-packages.yml` is an independent package-only path
for JPEG，schema，and serial-transport dependencies．It excludes every account，
USB，directory，service，SSH，and firewall role．

## Device boundary

USB rules set only group ownership and mode for known VID/PID pairs．They do not
create alternate symlinks．Jobs use `/dev/serial/by-id` from ignored local
inventory and may use `/dev/serial/by-path` as a physical-port assertion．

Device firmware，camera pins，sensor settings，resolution transitions，and USB
framing belong to `ephy-cam`．This repository invokes an external reference root
and independently validates its staged output．

## Implementation state and proposals

Ansible host configuration，generic reference invocation，and artifact
validation are implemented．A production scheduler，device daemon，automatic
capture，and toolchain installer remain proposals．
