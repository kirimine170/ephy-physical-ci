# Camera validation host

## Scope

This runbook installs only Ubuntu packages used by camera reference validation:

- `python3-pil` for JPEG decode and dimensions．
- `python3-jsonschema` for capture-contract validation．
- `python3-serial` for USB CDC transport．
- `python3-venv` for future isolated application tooling．

It does not manage SSH，UFW，accounts，groups，udev，hostname，directories，or
systemd services．Ubuntu package revisions follow the security-updated 24.04
archive．Application toolchains remain pinned by their owning repository．

## Controller setup

Use Ubuntu 24.04 under WSL2 or another Linux controller．Keep host addresses，
SSH keys，privilege credentials，and complete USB paths in ignored local
inventory or outside the repository．

## Check and apply

Run check mode first and review every planned package change:

```bash
scripts/setup-camera-validation-host inventories/local/hosts.yml check \
  --limit hil-01 --ask-become-pass
```

Only after approval，apply the package-only playbook:

```bash
scripts/setup-camera-validation-host inventories/local/hosts.yml apply \
  --limit hil-01 --ask-become-pass
```

Verify the packages without capturing an image:

```bash
dpkg-query -W python3-pil python3-jsonschema python3-serial python3-venv
python3 -c 'from PIL import Image; import jsonschema, serial; print("ok")'
```

## Invoke an ephy-cam reference

Clone `ephy-cam` separately and pass its reference directory explicitly．Do not
copy firmware into this repository．Use the stable device path from ignored
local inventory．

```bash
scripts/run-camera-reference /path/to/ephy-cam/reference/xiao-esp32s3-sense \
  build /tmp/ephy-cam-build
scripts/run-camera-reference /path/to/ephy-cam/reference/xiao-esp32s3-sense \
  flash /dev/serial/by-id/LOCAL_DEVICE /tmp/ephy-cam-build
scripts/run-camera-reference /path/to/ephy-cam/reference/xiao-esp32s3-sense \
  capture /dev/serial/by-id/LOCAL_DEVICE /var/tmp/ephy-cam-staging
```

Validate the generated capture independently:

```bash
scripts/validate-camera-artifacts CAPTURE_DIRECTORY /path/to/ephy-cam \
  --source-id xiao-esp32s3-sense-01 --width 2048 --height 1536
```

The staging root must remain outside every Git checkout．
