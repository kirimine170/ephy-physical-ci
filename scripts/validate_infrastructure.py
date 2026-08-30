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


def validate_udev_boundary() -> list[str]:
    path = (
        ROOT
        / "roles"
        / "physical_ci_usb"
        / "templates"
        / "70-ephy-physical-ci-usb.rules.j2"
    )
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    if "SYMLINK+=" in text:
        errors.append("custom udev symlinks must not compete with /dev/serial/by-id")
    if "ATTRS{serial}" in text:
        errors.append("full USB serials must stay in ignored local inventory")
    for required in ('SUBSYSTEM=="tty"', 'GROUP="{{ physical_ci_group }}"'):
        if required not in text:
            errors.append(f"udev template is missing {required}")
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
