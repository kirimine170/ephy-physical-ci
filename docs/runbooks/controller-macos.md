# macOS Ansible controller

## Scope

macOS can act as the Ansible controller for `hil-01`．The managed host remains
Ubuntu 24.04．No Physical CI build，flash，or capture command runs on the Mac．
The Mac needs Python 3，Git，OpenSSH，and network reachability to the host for
administrative applies．

## Setup

From the real `ephy-physical-ci` checkout，create an isolated controller
environment:

```bash
python3 -m venv .controller-venv
. .controller-venv/bin/activate
python -m pip install -r requirements-controller.txt
ansible-galaxy collection install -r requirements.yml
```

Copy `inventories/example/hosts.yml` and its `host_vars` into
`inventories/local/`，then add only the actual host address，SSH configuration，
and host-specific values to that ignored copy．Do not place a private key in the
repository．

## Preview

Keep the current SSH session open and run the same audit and check-mode gates as
the Linux controller:

```bash
ansible-inventory -i inventories/local/hosts.yml --graph
ansible-playbook -i inventories/local/hosts.yml playbooks/audit.yml
ansible-playbook -i inventories/local/hosts.yml playbooks/site.yml \
  --check --diff --ask-become-pass --limit hil-01
```

The GitHub Actions runner does not provide an administrative shell．After it is
installed，routine build and test dispatch works through outbound HTTPS even
when the Mac and `hil-01` are on different networks．A separate approved VPN or
other private administrative path is still required for later Ansible changes．
