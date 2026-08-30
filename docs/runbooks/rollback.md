# Rollback

## Baseline handling

Rollback archives are host-local operational data and must never enter Git．They may contain `/etc/shadow` password hashes，authorized keys，network configuration，and full USB serials．Store them under an access-controlled directory outside the checkout and record SHA-256 separately．

## First-apply rollback scope

The safe first apply can add packages，three accounts，the `hil-ci` group，directories，one udev rule，the USB capture utility，and a tmpfiles declaration．It does not change SSH，UFW，or `hil`．If verification fails:

1. Keep the original SSH session open and save the Ansible output．
2. Stop; do not run the SSH or firewall playbooks．
3. Re-run `site.yml --check --diff` to determine drift．
4. Remove only newly added Physical CI files，accounts，and directories after preserving artifacts．
5. Restore individual configuration files from the verified archive as needed．

Do not blindly extract `/etc/passwd`，`/etc/group`，`/etc/shadow`，or `/etc/gshadow` over a running multi-user system．Account database restoration requires single-user or recovery-mode coordination．Do not remove packages automatically during emergency rollback because other software may have started depending on them．

## SSH rollback

The SSH role is not part of the first apply．Its later playbook creates an Ansible backup，runs `sshd -t` against the complete configuration，and reloads rather than restarts the service．If validation fails，the role restores the previous drop-in and stops．Always retain a second verified administrator session before running it．
