# MCU toolchain manifest

## Boundary

`manifests/toolchains.json` is the future installation lock boundary．Every downloadable component must declare an exact version，HTTPS source，lowercase SHA-256，supported Linux platform，and relative installation directory．Board profiles reference component IDs and USB VID/PID pairs．

The committed baseline has `installation_enabled: false` and no components．It records board profiles but installs no XIAO-specific SDK，compiler，board package，flash utility，or firmware．This keeps host bootstrapping separate from toolchain selection．

## Future change requirements

A toolchain-enabling change must:

1. Add exact component versions and archive checksums．
2. Add an Ansible installer that downloads to a temporary path and verifies SHA-256 before extraction．
3. Install under a versioned `/opt/ephy-physical-ci/toolchains/<component>/<version>/` directory．
4. Avoid mutable global package-manager state in operator home directories．
5. Add a smoke test that reports the installed tool version without connecting to or flashing hardware．
6. Keep board core indexes，tokens，signing keys，and credentials outside Git．

Flash and test operations remain a later responsibility．The manifest does not authorize the optional systemd service or any daemon．
