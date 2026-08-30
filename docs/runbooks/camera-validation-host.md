# Camera validation host packages

## Scope

This runbook installs only the Ubuntu packages used to validate camera output on a Physical CI node．It does not
manage SSH，UFW，users，groups，udev rules，hostname，timezone，directories，or systemd services．Use it when the full
`playbooks/site.yml` apply is not approved．

The package set is declared in
`roles/physical_ci_camera_validation/defaults/main.yml`:

- `python3-pil` provides JPEG decoding and dimension inspection．
- `python3-jsonschema` validates generated `MediaEnvelope` documents．
- `python3-venv` provides an isolated Python environment boundary for future repository-owned tools．

Package revisions follow the security-updated Ubuntu 24.04 archives．Application-level Python dependencies that
require byte-for-byte version locking belong in the owning application repository，not in this host role．

## Controller setup

Use Ubuntu 24.04 under WSL2 or another Linux controller and prepare it as described in
[the WSL2 controller runbook](controller-wsl2.md)．Keep real host addresses，SSH keys，and privilege credentials in
ignored local inventory or outside the repository．

## Preview

Run the wrapper in `check` mode first:

```bash
scripts/setup-camera-validation-host inventories/local/hosts.yml check \
  --limit hil-01 --ask-become-pass
```

The expected writes are limited to APT cache metadata and packages from
`physical_ci_camera_validation_packages`，including their Ubuntu-managed dependencies．Review the complete
`--check --diff` result before applying．

## Apply and verify

After approval，run:

```bash
scripts/setup-camera-validation-host inventories/local/hosts.yml apply \
  --limit hil-01 --ask-become-pass
```

Verify the installed package state and imports without capturing an image:

```bash
dpkg-query -W python3-pil python3-jsonschema python3-venv
python3 -c 'from PIL import Image; import jsonschema; print(Image.__version__, jsonschema.__version__)'
```

Store host-specific command output outside Git if it contains network or hardware identifiers．
