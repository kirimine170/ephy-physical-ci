# Inventory boundary

## Tracked inventory

`inventories/sanitized/host-facts.yml` records the reproducible capability baseline without routable addresses，network hardware identifiers，SSH keys，password hashes，or full USB serial numbers．VID/PID，product names，drivers，package presence，and security-state booleans are safe to track．

`inventories/example/` uses the RFC 5737 documentation address `192.0.2.10` and empty credential lists．It exists for syntax validation and must not be used against a real host．

## Local inventory

Copy the example inventory to `inventories/local/` and replace values there．The complete directory is ignored except for its policy files．A local host variable file may contain:

- The real `ansible_host` and bootstrap account．
- A controller-only private-key path．
- Administrator and operator public keys．
- An administrator password hash or explicit NOPASSWD decision．
- Full `/dev/serial/by-id` links used by audit assertions．
- An approved SSH firewall CIDR．

Do not place plaintext login or become passwords in a file．Use `--ask-become-pass` or an approved external secret source．

## USB identity

The tracked model list grants tty access by VID/PID only．The ignored `physical_ci_expected_devices` list binds logical device IDs to the built-in `/dev/serial/by-id` paths．The udev role deliberately does not produce custom aliases．
