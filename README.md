# ephy-physical-ci

## Overview

Physical-device build，flash，test，and result-collection infrastructure for Ephy

## Role in the Ephy ecosystem

This repository is an Ephy `integration` project．Its status is `design` and its intended visibility is `public`．Repository relationships are declared in `.ephy/project.yaml`．

## Goals

- Describe the outcomes this repository owns．
- Keep responsibilities aligned with its declared Ephy project type．

## Non-goals

- Do not duplicate responsibilities owned by related repositories．
- Do not maintain a downstream repository registry in this repository．

## Current status

The current implementation status is `design`．This label describes observed implementation state，not a delivery date or completion percentage．

## Architecture

The design coordinates build，flash，test，and result collection through the authorized `ephy-worker` boundary．No production device orchestration is implemented yet．See [the physical CI boundary](docs/physical-ci-boundary.md)．

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

Add project-specific setup instructions here after selecting the implementation stack．

## Testing

Document project-specific test commands here．Keep the repository metadata validation in the standard verification path:

```bash
python3 scripts/validate_repository.py
```

## Security and data handling

The data classification is `internal`．Do not commit secrets，unnecessary personal data，raw conversation history，production Karte data，master camera images，raw LoRA training data，or model weights．See [docs/security-and-data.md](docs/security-and-data.md)．

## Documentation

- [Architecture](docs/architecture.md)
- [Repository relationships](docs/repository-relations.md)
- [Security and data handling](docs/security-and-data.md)
- [Architecture Decision Records](docs/adr/README.md)

## License

No license has been selected automatically．Determine the repository's visibility and license explicitly before distribution，then add the appropriate license file and update this section．
