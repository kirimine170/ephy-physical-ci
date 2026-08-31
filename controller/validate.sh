#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ANSIBLE_CONFIG="${repo_root}/ansible.cfg"
cd "${repo_root}"

python -m unittest discover -s tests -v
python scripts/validate_repository.py --check-sensitive-patterns
python scripts/validate_infrastructure.py
yamllint .
ansible-lint

for playbook in playbooks/*.yml; do
  ansible-playbook -i inventories/example/hosts.yml "${playbook}" --syntax-check
done

shellcheck \
  roles/physical_ci_usb/files/capture-usb-baseline \
  scripts/setup-camera-validation-host \
  scripts/run-camera-reference
python -c \
  'compile(open("scripts/validate-camera-artifacts").read(), "validator", "exec")'

ansible localhost -i localhost, -c local \
  -m ansible.builtin.template \
  -a "src=roles/physical_ci_service/templates/ephy-physical-ci-agent.service.j2 dest=/tmp/ephy-physical-ci-agent.service" \
  -e physical_ci_agent_command=/usr/bin/true \
  -e physical_ci_agent_user=hil-agent \
  -e physical_ci_group=hil-ci
systemd-analyze verify /tmp/ephy-physical-ci-agent.service

ansible localhost -i localhost, -c local \
  -m ansible.builtin.template \
  -a "src=roles/physical_ci_usb/templates/70-ephy-physical-ci-usb.rules.j2 dest=/tmp/70-ephy-physical-ci-usb.rules" \
  -e @roles/physical_ci_usb/defaults/main.yml \
  -e physical_ci_group=root
if udevadm --help 2>&1 | grep -q 'verify'; then
  udevadm verify /tmp/70-ephy-physical-ci-usb.rules
else
  echo "udevadm verify is unavailable; repository USB-rule validation already passed."
fi
