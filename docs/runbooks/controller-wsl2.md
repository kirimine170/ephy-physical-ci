# WSL2 Ansible controller

## Supported controller

Run Ansible from Ubuntu 24.04 under WSL2 or another Linux environment．Native Windows is not supported because Ansible's control-node runtime and POSIX permission model are Linux-oriented．Docker Desktop with its WSL2 Linux backend may be used for validation，but a normal Ubuntu WSL2 distribution is preferred for host administration．

Keep the working checkout in the WSL2 Linux filesystem，for example `~/src/ephy-physical-ci`，rather than `/mnt/c`．This preserves modes，symlinks，and performance．

## Setup

```bash
sudo apt-get update
sudo apt-get install --yes git openssh-client python3-venv

git clone git@github.com:kirimine170/ephy-physical-ci.git ~/src/ephy-physical-ci
cd ~/src/ephy-physical-ci
python3 -m venv .controller-venv
. .controller-venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-controller.txt
ansible-galaxy collection install -r requirements.yml
```

Copy the required controller private key into `~/.ssh` inside WSL2 and set mode `0600`．Do not commit it or place it under the repository．Copy `inventories/example/` into `inventories/local/` and configure the real host only in the ignored copy．

## Required preview

```bash
ansible-inventory -i inventories/local/hosts.yml --graph
ansible-playbook -i inventories/local/hosts.yml playbooks/audit.yml
ansible-playbook -i inventories/local/hosts.yml playbooks/site.yml \
  --check --diff --ask-become-pass --limit hil-01
```

Do not run `playbooks/ssh-hardening.yml` or `playbooks/firewall.yml` during the first apply．

## Containerized validation fallback

When a normal Ubuntu WSL2 distribution is not available，Docker Desktop's WSL2 Linux backend can run the repository-only validators．The controller image pins its base image digest and Python dependencies:

```bash
docker build -f controller/Containerfile -t ephy-physical-ci-controller .
docker run --rm -v "$PWD:/workspace" ephy-physical-ci-controller controller/validate.sh
```

Use a normal WSL2 distribution for interactive host administration and `--ask-become-pass`．Do not bake SSH keys or inventory into the image．
