# Remote GitHub Actions control plane

## Implemented boundary

The optional `playbooks/github-actions-runner.yml` installs a GitHub Actions
self-hosted runner on Ubuntu 24.04 and runs it as the non-interactive
`hil-agent` account．The runner opens outbound HTTPS connections to GitHub on
TCP port 443，so build and test dispatch does not require a public host address，
router port forwarding，or inbound GitHub access．This execution path is direct
to the Physical CI host and does not use `ephy-worker`．

The public `ephy-physical-ci` repository must not own the runner registration．
Create a dedicated private control repository and copy
the workflows under `examples/control-repository/.github/workflows/` into it．
The examples have an additional private-repository guard，use only manual
dispatch，pin checkout actions to a commit，serialize access to `hil-01`，and
remove per-job temporary state．Do not add `pull_request` or untrusted repository
inputs to a workflow that targets this persistent host．

## Prerequisites

1. Apply `playbooks/site.yml` first and verify the `hil-agent` account，group，
   directories，and existing recovery access as described in
   [First apply](first-apply.md)．
2. Create a dedicated private GitHub repository for Physical CI control．Do not
   reuse `ephy-private` because that repository must never be distributed to a
   worker or CI host．
3. In the private repository，open **Settings → Actions → Runners → New
   self-hosted runner** and obtain a short-lived registration token．
4. Confirm that the host can make outbound HTTPS connections to GitHub．Do not
   open a new inbound firewall port for the runner．

GitHub recommends self-hosted runners only for private repositories because a
public fork can otherwise attempt to execute dangerous code on a persistent
host．See the official
[self-hosted runner security guidance](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/manage-access)
and
[communication requirements](https://docs.github.com/en/actions/reference/runners/self-hosted-runners)．

## Local inventory

Set these values only in ignored `inventories/local/host_vars/hil-01.yml`．The
URL is configuration，not a credential，but the private-repository confirmation
is an explicit safety gate:

```yaml
physical_ci_github_runner_install: true
physical_ci_github_runner_enabled: true
physical_ci_github_runner_control_repository_private: true
physical_ci_github_runner_repository_url: >-
  https://github.com/YOUR_ACCOUNT/ephy-physical-ci-control
```

If the GitHub registration-token exchange succeeds but an authenticated
Actions tenant `ConnectionData` request times out before receiving any bytes，
test a smaller interface MTU reversibly before changing persistent networking．
When that comparison proves MTU 1400 is required，keep the network responsibility
outside the runner role and opt into the dedicated playbook:

```yaml
physical_ci_network_mtu_manage: true
physical_ci_network_mtu_interface: enp1s0
physical_ci_network_mtu: 1400
```

Preview and apply this separately，while recovery access to the host is
available:

```zsh
ansible-playbook -i inventories/local/hosts.yml \
  playbooks/network-mtu.yml \
  --check --diff --ask-become-pass --limit hil-01
ansible-playbook -i inventories/local/hosts.yml \
  playbooks/network-mtu.yml \
  --diff --ask-become-pass --limit hil-01
```

The role writes an isolated Netplan fragment，validates the merged configuration，
and then applies it．It is disabled by default and is intentionally excluded from
`site.yml` because an MTU change can affect the administrative connection．

If IPv4 GitHub connectivity succeeds but the runner diagnostic log repeatedly
times out in `GetConnect` with `SocketException` while the host has no usable
IPv6 route，set the following host-local override:

```yaml
physical_ci_github_runner_disable_ipv6: true
```

This sets `.NET`'s `DOTNET_SYSTEM_NET_DISABLEIPV6=1` for runner registration and
the runner service only．It does not change the host network configuration．Keep
the default `false` when IPv6 works．

Do not store the registration token in YAML．Preview the host changes first:

```zsh
ansible-playbook -i inventories/local/hosts.yml \
  playbooks/github-actions-runner.yml \
  --check --diff --ask-become-pass --limit hil-01
```

After reviewing the preview，read the token without echo，export it for the first
real apply，then remove it from the environment:

```zsh
read -s 'EPHY_GITHUB_RUNNER_TOKEN?Runner registration token: '
export EPHY_GITHUB_RUNNER_TOKEN
ansible-playbook -i inventories/local/hosts.yml \
  playbooks/github-actions-runner.yml \
  --ask-become-pass --limit hil-01
unset EPHY_GITHUB_RUNNER_TOKEN
```

The first command previews host changes but cannot preview GitHub registration
semantics．Review it before the real apply．The Ansible registration task hides
its command and output，and later convergent applies do not require the token
while the local `.runner` registration exists．

## Verify remote dispatch

Copy the example workflow into the private control repository，commit it there，
and confirm that `hil-01` is online with custom labels `ephy-physical-ci` and
`hil-01`．Then dispatch the smoke test from GitHub or with GitHub CLI:

```bash
gh workflow run physical-ci-smoke.yml \
  --repo YOUR_ACCOUNT/ephy-physical-ci-control \
  -f infrastructure_revision=main
```

The smoke workflow creates an isolated virtual environment，runs the complete
repository validation，and deletes its temporary dependency and Ansible state
even after failure．It does not flash a device or publish camera artifacts．

The camera workflow requires the ignored stable device path to be stored as the
private control repository secret `PHYSICAL_CI_SERIAL_DEVICE`．It captures one
QXGA JPEG with the firmware already installed on the XIAO，validates its JPEG and
metadata contracts，writes only dimensions and byte count to the job summary，
and deletes the JPEG in the unconditional cleanup step．It neither flashes the
device nor uploads an artifact．Install the package-only camera validation role
before the first camera dispatch:

```bash
ansible-playbook -i inventories/local/hosts.yml \
  playbooks/camera-validation-packages.yml \
  --ask-become-pass --limit hil-01
```

Dispatch it with reviewed revisions only:

```bash
gh workflow run physical-ci-camera-capture.yml \
  --repo YOUR_ACCOUNT/ephy-physical-ci-control \
  -f infrastructure_revision=main \
  -f camera_revision=main
```

Hardware workflows must retain the same private，manual，concurrency，stable
device identity，and unconditional cleanup gates．

## Update and recovery

The initial runner archive and both supported architecture checksums are pinned
in the Ansible role．After registration，the runner uses GitHub's built-in
security update mechanism．Do not disable it．If GitHub shows the runner as
offline，inspect the service locally or over the approved administrative path:

```bash
sudo systemctl status ephy-physical-ci-agent.service
sudo journalctl -u ephy-physical-ci-agent.service --since today
```

Removing or replacing a registration is an explicit operational action because
it changes GitHub and host credentials．Use GitHub's removal token and the
runner's `config.sh remove` procedure．Do not delete `.credentials` alone．
