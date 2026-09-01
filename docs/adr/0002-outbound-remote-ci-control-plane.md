# ADR 0002: Outbound remote CI control plane

## Status

Accepted．

## Context

The Physical CI host and its operator Mac may be on different networks．The host
must accept reviewed build and test jobs without exposing SSH or an application
port to the public internet．The `ephy-physical-ci` repository is public，and a
persistent self-hosted runner executing public pull requests would expose the
host and attached devices to untrusted code．Physical CI execution is separate
from the OS-level Ephy tasks implemented by `ephy-worker`．

## Decision

- Use a persistent GitHub Actions runner that initiates outbound HTTPS from the
  Physical CI host．
- Register it only to a dedicated private control repository，never directly to
  the public infrastructure or firmware repositories．
- Accept jobs only through reviewed workflows in that control repository．The
  initial workflow is manually dispatched，has a private-repository guard，uses
  dedicated runner labels，and serializes the single hardware host．
- Supply the short-lived registration token from the controller environment．
  Never store it in Git or inventory．
- Run the service as `hil-agent` with the existing systemd hardening and USB
  group boundary．
- Keep interactive administration separate．The runner is a job channel，not a
  replacement for an approved VPN or private SSH path．
- Dispatch directly to the Physical CI host．Do not route jobs through or declare
  a dependency on `ephy-worker`．
- The first camera job captures and validates one image without flashing the
  device or uploading raw media．Its stable `/dev/serial/by-id` path is supplied
  by the private control repository and its temporary image is always deleted．

## Consequences

Routine build and test dispatch works across NAT and changing operator networks
without an inbound firewall exception．The private control repository becomes a
security boundary and its collaborators and workflows require careful review．A
persistent runner retains host state between jobs，so every workflow must isolate
and clean job data and must never execute untrusted pull requests．Initial GitHub
repository creation，registration，and any later deregistration remain explicit
operator actions．
