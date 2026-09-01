#!/usr/bin/env python3
"""Validate Physical CI infrastructure boundaries without contacting a host."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


ROOT = Path(__file__).resolve().parents[1]
IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
USB_ID = re.compile(r"^[a-f0-9]{4}:[a-f0-9]{4}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
GITHUB_RUNNER_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")

SENSITIVE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"(?im)^\s*ansible_(?:become_)?password\s*:"),
    re.compile(r"(?im)^\s*ansible_ssh_private_key_file\s*:"),
    re.compile(r"ssh-(?:ed25519|rsa)\s+AAAA[0-9A-Za-z+/]+"),
)


def repository_files(root: Path = ROOT) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [root / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def text_files(paths: Iterable[Path]) -> Iterable[tuple[Path, str]]:
    for path in paths:
        try:
            yield path, path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue


def validate_no_tracked_local_inventory(files: list[Path]) -> list[str]:
    allowed = {
        ROOT / "inventories" / "local" / ".gitignore",
        ROOT / "inventories" / "local" / "README.md",
    }
    return [
        f"tracked local inventory is prohibited: {path.relative_to(ROOT)}"
        for path in files
        if ROOT / "inventories" / "local" in path.parents and path not in allowed
    ]


def validate_sensitive_patterns(files: list[Path]) -> list[str]:
    errors: list[str] = []
    for path, text in text_files(files):
        if path.resolve() == Path(__file__).resolve():
            # This validator necessarily contains the literal signatures it scans.
            continue
        for pattern in SENSITIVE_PATTERNS:
            if pattern.search(text):
                errors.append(
                    f"sensitive pattern {pattern.pattern!r} in {path.relative_to(ROOT)}"
                )
    return errors


def validate_sanitized_inventory() -> list[str]:
    path = ROOT / "inventories" / "sanitized" / "host-facts.yml"
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    if "address: redacted" not in text or "hardware_address: redacted" not in text:
        errors.append("sanitized inventory must redact network identifiers")
    if text.count("serial: redacted") != 3:
        errors.append("sanitized inventory must redact every USB serial")
    if "/dev/serial/by-id/" in text:
        errors.append("sanitized inventory must not contain full by-id links")
    return errors


def validate_safe_playbook_boundary() -> list[str]:
    path = ROOT / "playbooks" / "site.yml"
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    for forbidden in ("physical_ci_ssh", "physical_ci_firewall"):
        if forbidden in text:
            errors.append(f"site.yml must not include connection-sensitive role {forbidden}")
    if re.search(r"\bhil\b", text):
        errors.append("site.yml must not modify the legacy hil account")
    return errors


def validate_camera_validation_package_boundary() -> list[str]:
    playbook_path = ROOT / "playbooks" / "camera-validation-packages.yml"
    defaults_path = (
        ROOT
        / "roles"
        / "physical_ci_camera_validation"
        / "defaults"
        / "main.yml"
    )
    tasks_path = (
        ROOT
        / "roles"
        / "physical_ci_camera_validation"
        / "tasks"
        / "main.yml"
    )
    playbook = playbook_path.read_text(encoding="utf-8")
    defaults = defaults_path.read_text(encoding="utf-8")
    tasks = tasks_path.read_text(encoding="utf-8")
    errors: list[str] = []

    required_packages = {
        "python3-jsonschema",
        "python3-pil",
        "python3-serial",
        "python3-venv",
    }
    for package in required_packages:
        if f"  - {package}\n" not in defaults:
            errors.append(f"camera validation package list is missing {package}")

    if "role: physical_ci_camera_validation" not in playbook:
        errors.append("camera validation playbook must use its package-only role")
    for forbidden in (
        "physical_ci_accounts",
        "physical_ci_base",
        "physical_ci_directories",
        "physical_ci_firewall",
        "physical_ci_service",
        "physical_ci_ssh",
        "physical_ci_usb",
    ):
        if forbidden in playbook:
            errors.append(
                "camera validation playbook includes out-of-scope role "
                f"{forbidden}"
            )
    if "ansible.builtin.apt:" not in tasks or "state: present" not in tasks:
        errors.append("camera validation role must only declare present APT packages")
    return errors


def validate_camera_reference_boundary(files: list[Path] | None = None) -> list[str]:
    files = files or repository_files()
    errors: list[str] = []
    implementation_suffixes = {".ino", ".c", ".cc", ".cpp"}
    for path in files:
        if path.suffix.lower() in implementation_suffixes:
            errors.append(
                "Physical CI must not own camera device implementation: "
                f"{path.relative_to(ROOT)}"
            )

    runner = (ROOT / "scripts" / "run-camera-reference").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "OV3660",
        "303a:1001",
        "/dev/serial/by-id/usb-",
        "192.168.",
    ):
        if forbidden in runner:
            errors.append(f"camera reference runner contains device detail {forbidden}")
    for required in ("REFERENCE_ROOT", "build", "flash", "capture"):
        if required not in runner:
            errors.append(f"camera reference runner is missing {required}")
    return errors


def validate_remote_ci_boundary() -> list[str]:
    defaults_path = (
        ROOT
        / "roles"
        / "physical_ci_github_runner"
        / "defaults"
        / "main.yml"
    )
    tasks_path = (
        ROOT
        / "roles"
        / "physical_ci_github_runner"
        / "tasks"
        / "main.yml"
    )
    playbook_path = ROOT / "playbooks" / "github-actions-runner.yml"
    site_path = ROOT / "playbooks" / "site.yml"
    workflow_path = (
        ROOT
        / "examples"
        / "control-repository"
        / ".github"
        / "workflows"
        / "physical-ci-smoke.yml"
    )
    camera_workflow_path = (
        ROOT
        / "examples"
        / "control-repository"
        / ".github"
        / "workflows"
        / "physical-ci-camera-capture.yml"
    )
    defaults = defaults_path.read_text(encoding="utf-8")
    tasks = tasks_path.read_text(encoding="utf-8")
    playbook = playbook_path.read_text(encoding="utf-8")
    site = site_path.read_text(encoding="utf-8")
    workflow = workflow_path.read_text(encoding="utf-8")
    camera_workflow = camera_workflow_path.read_text(encoding="utf-8")
    errors: list[str] = []

    required_defaults = (
        "physical_ci_github_runner_install: false",
        "physical_ci_github_runner_enabled: false",
        "physical_ci_github_runner_control_repository_private: false",
        "lookup('ansible.builtin.env', 'EPHY_GITHUB_RUNNER_TOKEN')",
    )
    for required in required_defaults:
        if required not in defaults:
            errors.append(f"GitHub runner defaults are missing {required}")

    version_match = re.search(
        r"physical_ci_github_runner_bootstrap_version:\s*([^\s]+)", defaults
    )
    if not version_match or not GITHUB_RUNNER_VERSION.fullmatch(
        version_match.group(1)
    ):
        errors.append("GitHub runner bootstrap version must be exact")

    checksum_matches = re.findall(r"^\s+sha256:\s*([a-f0-9]+)$", defaults, re.MULTILINE)
    if len(checksum_matches) != 2 or any(
        not SHA256.fullmatch(checksum) for checksum in checksum_matches
    ):
        errors.append("GitHub runner must pin valid x86_64 and aarch64 checksums")

    if "physical_ci_github_runner_control_repository_private | bool" not in tasks:
        errors.append("GitHub runner must require a confirmed private control repository")
    if "checksum: \"sha256:{{ physical_ci_github_runner_archive.sha256 }}\"" not in tasks:
        errors.append("GitHub runner download must verify its pinned checksum")
    if tasks.count("no_log: true") < 3:
        errors.append("GitHub runner registration and credentials must suppress logs")
    if "role: physical_ci_github_runner" not in playbook:
        errors.append("the explicit GitHub runner playbook must use its runner role")
    directories_role = playbook.find("role: physical_ci_directories")
    runner_role = playbook.find("role: physical_ci_github_runner")
    if directories_role < 0 or directories_role > runner_role:
        errors.append("the GitHub runner playbook must provision service directories first")
    if "physical_ci_github_runner_root }}/run.sh" not in playbook:
        errors.append("the GitHub runner service must use the packaged run.sh entry point")
    if "physical_ci_github_runner_root }}/runsvc.sh" in playbook:
        errors.append("the GitHub runner service must not assume svc.sh created runsvc.sh")
    if 'path: "{{ physical_ci_github_runner_root }}/run.sh"' not in tasks:
        errors.append("the GitHub runner role must verify its service entry point")
    if "physical_ci_github_runner" in site:
        errors.append("site.yml must not implicitly install a remote control plane")

    required_workflow_guards = (
        "workflow_dispatch:",
        "github.event.repository.private == true",
        "cancel-in-progress: false",
        "- self-hosted",
        "- ephy-physical-ci",
        "- hil-01",
        "if: always()",
        "Refusing unsafe cleanup path",
    )
    for required in required_workflow_guards:
        if required not in workflow:
            errors.append(f"remote CI workflow is missing safety guard {required}")
    for unsafe_trigger in ("push", "pull_request", "pull_request_target"):
        if re.search(rf"^\s{{2}}{unsafe_trigger}:\s*$", workflow, re.MULTILINE):
            errors.append(f"remote CI workflow must not use {unsafe_trigger}")
    checkout_match = re.search(r"uses: actions/checkout@([a-f0-9]+)", workflow)
    if not checkout_match or len(checkout_match.group(1)) != 40:
        errors.append("remote CI workflow must pin actions/checkout to a commit")

    required_camera_guards = (
        "workflow_dispatch:",
        "github.event.repository.private == true",
        "cancel-in-progress: false",
        "- self-hosted",
        "- ephy-physical-ci",
        "- hil-01",
        "secrets.PHYSICAL_CI_SERIAL_DEVICE",
        "/dev/serial/by-id/",
        "validate-camera-artifacts",
        "retrieve_image:",
        "default: false",
        "if: ${{ inputs.retrieve_image }}",
        "retention-days: 1",
        "if: always()",
        "Refusing unsafe cleanup path",
    )
    for required in required_camera_guards:
        if required not in camera_workflow:
            errors.append(f"camera CI workflow is missing safety guard {required}")
    for unsafe_trigger in ("push", "pull_request", "pull_request_target"):
        if re.search(
            rf"^\s{{2}}{unsafe_trigger}:\s*$", camera_workflow, re.MULTILINE
        ):
            errors.append(f"camera CI workflow must not use {unsafe_trigger}")
    camera_checkout_matches = re.findall(
        r"uses: actions/checkout@([a-f0-9]+)", camera_workflow
    )
    if len(camera_checkout_matches) != 2 or any(
        len(checkout) != 40 for checkout in camera_checkout_matches
    ):
        errors.append("camera CI workflow must pin both checkout actions")
    artifact_matches = re.findall(
        r"uses: actions/upload-artifact@([a-f0-9]+)", camera_workflow
    )
    if len(artifact_matches) != 1 or len(artifact_matches[0]) != 40:
        errors.append("camera CI workflow must pin one private retrieval action")
    for forbidden in ("run-camera-reference flash",):
        if forbidden in camera_workflow:
            errors.append(f"camera CI workflow must not contain {forbidden}")

    project = (ROOT / ".ephy" / "project.yaml").read_text(encoding="utf-8")
    boundary = (ROOT / "docs" / "physical-ci-boundary.md").read_text(
        encoding="utf-8"
    )
    if 'depends_on: ["ephy-worker"]' in project or 'runs_on: ["ephy-worker"]' in project:
        errors.append("Physical CI must not declare an ephy-worker dependency")
    if (
        "entry points through `ephy-worker`" in boundary
        or "`ephy-worker` owns authorized remote execution" in boundary
    ):
        errors.append("Physical CI must not route remote jobs through ephy-worker")
    return errors


def validate_network_mtu_boundary() -> list[str]:
    defaults_path = (
        ROOT / "roles" / "physical_ci_network_mtu" / "defaults" / "main.yml"
    )
    tasks_path = ROOT / "roles" / "physical_ci_network_mtu" / "tasks" / "main.yml"
    handlers_path = (
        ROOT / "roles" / "physical_ci_network_mtu" / "handlers" / "main.yml"
    )
    template_path = (
        ROOT
        / "roles"
        / "physical_ci_network_mtu"
        / "templates"
        / "90-ephy-physical-ci-mtu.yaml.j2"
    )
    playbook_path = ROOT / "playbooks" / "network-mtu.yml"
    site_path = ROOT / "playbooks" / "site.yml"

    defaults = defaults_path.read_text(encoding="utf-8")
    tasks = tasks_path.read_text(encoding="utf-8")
    handlers = handlers_path.read_text(encoding="utf-8")
    template = template_path.read_text(encoding="utf-8")
    playbook = playbook_path.read_text(encoding="utf-8")
    site = site_path.read_text(encoding="utf-8")
    errors: list[str] = []

    if "physical_ci_network_mtu_manage: false" not in defaults:
        errors.append("network MTU management must be disabled by default")
    if "ansible_default_ipv4.interface" not in tasks:
        errors.append("network MTU role must require the default IPv4 interface")
    if "physical_ci_network_mtu | int >= 1280" not in tasks:
        errors.append("network MTU role must preserve the IPv6 minimum MTU")
    if "role: physical_ci_network_mtu" not in playbook:
        errors.append("the explicit network MTU playbook must use its role")
    if "physical_ci_network_mtu" in site:
        errors.append("site.yml must not implicitly change the host network MTU")
    for required in ("netplan", "generate", "apply"):
        if required not in handlers:
            errors.append(f"network MTU handlers are missing {required}")
    for required in (
        "physical_ci_network_mtu_interface",
        "physical_ci_network_mtu",
    ):
        if required not in template:
            errors.append(f"network MTU template is missing {required}")
    return errors


def validate_udev_boundary() -> list[str]:
    defaults_path = ROOT / "roles" / "physical_ci_usb" / "defaults" / "main.yml"
    template_path = (
        ROOT
        / "roles"
        / "physical_ci_usb"
        / "templates"
        / "70-ephy-physical-ci-usb.rules.j2"
    )
    playbook_path = ROOT / "playbooks" / "usb-access.yml"
    defaults = defaults_path.read_text(encoding="utf-8")
    text = template_path.read_text(encoding="utf-8")
    playbook = playbook_path.read_text(encoding="utf-8")
    errors: list[str] = []
    if "SYMLINK+=" in text:
        errors.append("custom udev symlinks must not compete with /dev/serial/by-id")
    if "ATTRS{serial}" in text:
        errors.append("full USB serials must stay in ignored local inventory")
    for required in ('SUBSYSTEM=="tty"', 'GROUP="{{ physical_ci_group }}"'):
        if required not in text:
            errors.append(f"udev template is missing {required}")
    if "physical_ci_agent_user: hil-agent" not in defaults:
        errors.append("USB role must define its pre-provisioned agent account")
    if "role: physical_ci_usb" not in playbook:
        errors.append("the explicit USB access playbook must use its USB role")
    for forbidden in (
        "physical_ci_firewall",
        "physical_ci_github_runner",
        "physical_ci_network_mtu",
        "physical_ci_service",
        "physical_ci_ssh",
    ):
        if forbidden in playbook:
            errors.append(f"USB access playbook includes out-of-scope role {forbidden}")
    return errors


def validate_toolchain_manifest(
    path: Path | None = None,
    schema_path: Path | None = None,
) -> list[str]:
    path = path or ROOT / "manifests" / "toolchains.json"
    schema_path = schema_path or ROOT / "manifests" / "toolchains.schema.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        return [f"invalid committed toolchain schema: {error.message}"]

    validator = Draft202012Validator(schema)
    schema_errors = sorted(
        validator.iter_errors(data),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    for error in schema_errors:
        location = "$"
        if error.absolute_path:
            location += "." + ".".join(str(part) for part in error.absolute_path)
        errors.append(f"toolchain manifest schema violation at {location}: {error.message}")
    if errors:
        return errors

    if data.get("schema_version") != 1:
        errors.append("toolchain manifest schema_version must be 1")
    if data.get("installation_enabled") is not False:
        errors.append("toolchain installation must remain disabled in the baseline")

    components = data.get("components")
    if not isinstance(components, list):
        return errors + ["toolchain components must be a list"]
    component_ids: set[str] = set()
    for index, component in enumerate(components):
        component_id = component.get("id")
        if not isinstance(component_id, str) or not IDENTIFIER.fullmatch(component_id):
            errors.append(f"components[{index}].id is invalid")
            continue
        if component_id in component_ids:
            errors.append(f"duplicate component id: {component_id}")
        component_ids.add(component_id)
        if not component.get("version"):
            errors.append(f"component {component_id} needs an exact version")
        if not str(component.get("source_url", "")).startswith("https://"):
            errors.append(f"component {component_id} needs an HTTPS source URL")
        if not SHA256.fullmatch(str(component.get("sha256", ""))):
            errors.append(f"component {component_id} needs a lowercase SHA-256")
        install_subdir = Path(str(component.get("install_subdir", "")))
        if install_subdir.is_absolute() or ".." in install_subdir.parts:
            errors.append(f"component {component_id} install_subdir escapes its root")

    profiles = data.get("board_profiles")
    if not isinstance(profiles, list):
        return errors + ["board_profiles must be a list"]
    profile_ids: set[str] = set()
    for index, profile in enumerate(profiles):
        profile_id = profile.get("id")
        if not isinstance(profile_id, str) or not IDENTIFIER.fullmatch(profile_id):
            errors.append(f"board_profiles[{index}].id is invalid")
            continue
        if profile_id in profile_ids:
            errors.append(f"duplicate board profile id: {profile_id}")
        profile_ids.add(profile_id)
        for usb_id in profile.get("usb_ids", []):
            if not USB_ID.fullmatch(str(usb_id)):
                errors.append(f"board profile {profile_id} has invalid USB ID {usb_id}")
        for component_id in profile.get("components", []):
            if component_id not in component_ids:
                errors.append(
                    f"board profile {profile_id} references unknown component {component_id}"
                )
    return errors


def validate() -> list[str]:
    files = repository_files()
    errors: list[str] = []
    errors.extend(validate_no_tracked_local_inventory(files))
    errors.extend(validate_sensitive_patterns(files))
    errors.extend(validate_sanitized_inventory())
    errors.extend(validate_safe_playbook_boundary())
    errors.extend(validate_camera_validation_package_boundary())
    errors.extend(validate_camera_reference_boundary(files))
    errors.extend(validate_remote_ci_boundary())
    errors.extend(validate_network_mtu_boundary())
    errors.extend(validate_udev_boundary())
    errors.extend(validate_toolchain_manifest())
    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Infrastructure validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
