# Legacy LXD membership

## Observed state

The installer-created `hil` account is a member of the `lxd` group．LXD group membership can become root-equivalent when an LXD daemon is installed and usable．The read-only 2026-08-30 audit found:

- `/usr/sbin/lxc` is present as Ubuntu's on-demand installer entry point．Invoking
  `lxc` can install the LXD snap，so it is not a read-only audit command on this host．
- No LXD snap is installed．
- No LXD Debian package is installed．
- No LXD process，instance storage，or instance was detected．
- `lxd-installer.socket` is enabled and listening．

The initial Ansible apply does not change `hil` or the installer socket．New accounts are never added to `lxd`．

## Future removal procedure

Treat removal as a separate approved maintenance change:

```bash
getent group lxd
snap list lxd
systemctl list-units --all | grep -i lxd
ps -ef | grep -E '[l]xd|[l]xc'
sudo find /var/snap/lxd /var/lib/lxd -mindepth 1 -maxdepth 2 -print
```

Do not run `lxc list` or another `lxc` subcommand until `snap list lxd` confirms
that LXD is already installed．On Ubuntu's installer stub，the command itself has
side effects．

If LXD remains unused，disable the on-demand installer socket if policy allows it，then remove `hil` from the group with `sudo gpasswd -d hil lxd`．Log out every `hil` session and verify `id hil` after a new login．Do not automate this in the first-apply playbook．
