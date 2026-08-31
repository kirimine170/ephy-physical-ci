# ephy-physical-ci

## Overview

Physical-device build，flash，test，and result-collection infrastructure for
Ephy．

## Role in the Ephy ecosystem

This repository is an Ephy `integration` project．Its status is `design` and
its intended visibility is `public`．Repository relationships are declared in
`.ephy/project.yaml`．

## Goals

- Reproduce an Ubuntu 24.04 Physical CI node through reviewable Ansible code．
- Separate administrator，operator，and future agent privileges．
- Preserve stable USB identity through `/dev/serial/by-id`．
- Provide generic build，flash，capture，and artifact-validation entry points．
- Define a versioned boundary for future MCU toolchains．

## Non-goals

- Do not own device firmware or camera sensor implementation．
- Do not ship a production scheduler or daemon in the current design state．
- Do not store host addresses，USB serial numbers，credentials，or private
  inventory in Git．

## Current status

The repository defines a reproducible host baseline，a package-only camera
validation playbook，generic reference-command wrappers，and staged artifact
validation．Production job orchestration is not implemented．

## Architecture

Ansible declares the host baseline，accounts，directories，minimal USB access，
and an optional hardened systemd unit．Connection-sensitive SSH and firewall
changes are isolated from the default playbook．Camera firmware，pins，sensor
settings，and USB framing remain in `ephy-cam`．See
[Architecture](docs/architecture.md) and
[the Physical CI boundary](docs/physical-ci-boundary.md)．

## Repository relationships

- Parent project: `ephy`
- Direct dependency: `ephy-worker`
- Integration peer: `ephy-runtime`
- Runtime platform: `ephy-worker`

Do not use Git submodules as an ecosystem relationship model．See
[docs/repository-relations.md](docs/repository-relations.md)．

## Getting started

Use Ubuntu 24.04 under WSL2 or another Linux controller．Do not run Ansible
natively on Windows．Prepare an ignored local inventory，then run the read-only
audit and check mode before any apply:

```bash
python3 -m venv .controller-venv
. .controller-venv/bin/activate
python -m pip install -r requirements-controller.txt
ansible-galaxy collection install -r requirements.yml
cp inventories/example/hosts.yml inventories/local/hosts.yml
cp -R inventories/example/host_vars inventories/local/
ansible-playbook -i inventories/local/hosts.yml playbooks/audit.yml
ansible-playbook -i inventories/local/hosts.yml playbooks/site.yml \
  --check --diff --ask-become-pass
```

For camera validation packages only，use
`scripts/setup-camera-validation-host`．This path does not manage SSH，UFW，
accounts，udev，hostname，directories，or services．See the
[camera validation runbook](docs/runbooks/camera-validation-host.md)．

## Testing

```bash
python3 -m unittest discover -s tests -v
python3 scripts/validate_repository.py --check-sensitive-patterns
python3 scripts/validate_infrastructure.py
yamllint .
ansible-lint
for playbook in playbooks/*.yml; do
  ansible-playbook -i inventories/example/hosts.yml "$playbook" --syntax-check
done
```

## Security and data handling

The data classification is `internal`．Do not commit secrets，unnecessary
personal data，raw conversations，production Karte data，camera master images，
raw training data，or model weights．See
[docs/security-and-data.md](docs/security-and-data.md)．

## Documentation

- [Architecture](docs/architecture.md)
- [Physical CI boundary](docs/physical-ci-boundary.md)
- [Inventory boundary](docs/inventory.md)
- [Toolchain manifest](docs/toolchain-manifest.md)
- [Operator runbooks](docs/runbooks/)
- [Security and data handling](docs/security-and-data.md)

## License

No license has been selected．Determine visibility and licensing explicitly
before distribution，then add a license file and update this section．
