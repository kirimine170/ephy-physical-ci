# ephy-physical-ci

## Overview

Physical-device build，flash，test，and result-collection infrastructure for Ephy

## Role in the Ephy ecosystem

This repository is an Ephy `integration` project．Its status is `design` and its intended visibility is `public`．Repository relationships are declared in `.ephy/project.yaml`．

## Goals

- Reproduce an Ubuntu 24.04 Physical CI node through reviewable Ansible code．
- Give administrators，operators，and future agents separate least-privilege identities．
- Preserve stable USB identity through the kernel-provided `/dev/serial/by-id` links．
- Provide a versioned boundary for future build，flash，test，and toolchain execution．

## Non-goals

- Do not duplicate responsibilities owned by related repositories．
- Do not maintain a downstream repository registry in this repository．
- Do not ship a production scheduler or device daemon in the current design state．
- Do not store host addresses，USB serial numbers，credentials，or private inventory in Git．

## Current status

The current implementation status is `design`．This label describes observed implementation state，not a delivery date or completion percentage．

## Architecture

Ansible declares the host baseline，accounts，directories，minimal USB access，and an optional hardened systemd unit．Connection-sensitive SSH and firewall changes are isolated from the default playbook．No production device orchestration is implemented yet．See [Architecture](docs/architecture.md) and [the physical CI boundary](docs/physical-ci-boundary.md)．

## Repository relationships

- Parent project: `ephy`
- Direct dependencies:
  - `ephy-worker`
- Integration peers:
  - `ephy-runtime`
- Runtime platforms:
  - `ephy-worker`

Declare only the parent and direct relationships．Do not list downstream consumers，and do not use Git submodules to represent ecosystem relationships．See [docs/repository-relations.md](docs/repository-relations.md)．

## Getting started

Use an Ubuntu 24.04 WSL2 distribution or another Linux controller．Do not run Ansible natively on Windows．Prepare the pinned controller environment and an ignored local inventory:

```bash
python3 -m venv .controller-venv
. .controller-venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-controller.txt
ansible-galaxy collection install -r requirements.yml
cp inventories/example/hosts.yml inventories/local/hosts.yml
cp -R inventories/example/host_vars inventories/local/
```

Run the read-only audit and the required preview before any real apply:

```bash
ansible-playbook -i inventories/local/hosts.yml playbooks/audit.yml
ansible-playbook -i inventories/local/hosts.yml playbooks/site.yml \
  --check --diff --ask-become-pass
```

See the [WSL2 controller runbook](docs/runbooks/controller-wsl2.md) and [first-apply runbook](docs/runbooks/first-apply.md)．

When only the JPEG and `MediaEnvelope` validation dependencies are approved，use the isolated package playbook:

```bash
scripts/setup-camera-validation-host inventories/local/hosts.yml check \
  --limit hil-01 --ask-become-pass
```

See the [camera validation host package runbook](docs/runbooks/camera-validation-host.md) before changing `check` to
`apply`．This path does not manage SSH，UFW，accounts，udev，hostname，directories，or services．

## Testing

Document project-specific test commands here．Keep the repository metadata validation in the standard verification path:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/validate_repository.py --check-sensitive-patterns
python3 scripts/validate_infrastructure.py
yamllint .
ansible-lint
ansible-playbook -i inventories/example/hosts.yml playbooks/site.yml --syntax-check
```

## Security and data handling

The data classification is `internal`．Do not commit secrets，unnecessary personal data，raw conversation history，production Karte data，master camera images，raw LoRA training data，or model weights．See [docs/security-and-data.md](docs/security-and-data.md)．

## Documentation

- [Architecture](docs/architecture.md)
- [Repository relationships](docs/repository-relations.md)
- [Security and data handling](docs/security-and-data.md)
- [Inventory boundary](docs/inventory.md)
- [Toolchain manifest](docs/toolchain-manifest.md)
- [Operator runbooks](docs/runbooks/)
- [Architecture Decision Records](docs/adr/README.md)

## License

No license has been selected automatically．Determine the repository's visibility and license explicitly before distribution，then add the appropriate license file and update this section．
