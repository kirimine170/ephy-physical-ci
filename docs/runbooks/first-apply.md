# First apply

## Safety contract

The first apply uses only `playbooks/site.yml`．It does not include the SSH or firewall roles and contains no task for the existing `hil` account．Keep an established SSH session open during every real apply．

## Before preview

1. Capture a rollback baseline outside the repository．Include account databases，SSH drop-ins，UFW，netplan，udev，systemd，and package state．Restrict its filesystem ACL because account password hashes may be present．
2. Verify the archive checksum after transfer and remove any remote temporary copy．
3. Populate ignored local inventory with administrator and operator public keys．
4. Supply the administrator password hash from an external source，or explicitly approve NOPASSWD．
5. Run the audit playbook and resolve missing `/dev/serial/by-id` links．
6. Confirm that reserved GID `980` and UIDs `980`，`2001`，and `2002` are
   either unused or already assigned to `hil-agent`，`hil-admin`，and
   `hil-operator` as declared．The playbook stops on a collision．

## Preview and review gate

```bash
ansible-playbook -i inventories/local/hosts.yml playbooks/site.yml \
  --check --diff --ask-become-pass --limit hil-01
```

Review every changed path and package before removing `--check`．A preview is not approval to apply．Record the output outside Git if it contains host data．

## First real apply

Run only after explicit human approval:

```bash
ansible-playbook -i inventories/local/hosts.yml playbooks/site.yml \
  --diff --ask-become-pass --limit hil-01
```

Then verify in separate sessions:

1. `hil-admin` key login and sudo．
2. `hil-operator` key login，sudo rejection，and read/write access through `/dev/serial/by-id`．
3. `hil-agent` has `/usr/sbin/nologin` and no interactive login．
4. The original `hil` session still works unchanged．

SSH and UFW remain outside this procedure．Manage either only through its separate playbook after a second approval and independent administrator access verification．
