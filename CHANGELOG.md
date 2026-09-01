# Changelog

All notable changes to this repository are documented in this file．

## Unreleased

### Added

- Reproducible Ubuntu 24.04 Physical CI host configuration through Ansible．
- Least-privilege account，directory，USB，and optional service roles．
- Sanitized host facts and rollback，WSL2，first-apply，and LXD runbooks．
- Disabled-by-default MCU toolchain lock manifest and infrastructure CI．
- Package-only camera validation setup for Ubuntu 24.04．
- Generic external camera-reference build，flash，and capture wrapper．
- Independent staged JPEG and contract artifact validator．
- Initial language-independent Ephy repository template and validators．
- Disabled-by-default outbound GitHub Actions runner provisioning and private
  control-repository smoke workflow．
- macOS controller and cross-network remote CI runbooks．
- Corrected the Physical CI boundary to remove the erroneous `ephy-worker`
  dependency and execution route．
