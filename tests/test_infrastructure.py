from __future__ import annotations

from pathlib import Path
import json
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_infrastructure


class InfrastructureValidationTests(unittest.TestCase):
    def test_repository_infrastructure_is_safe(self) -> None:
        self.assertEqual(validate_infrastructure.validate(), [])

    def test_initial_site_does_not_manage_remote_access(self) -> None:
        self.assertEqual(validate_infrastructure.validate_safe_playbook_boundary(), [])

    def test_udev_preserves_builtin_stable_links(self) -> None:
        self.assertEqual(validate_infrastructure.validate_udev_boundary(), [])

    def test_toolchain_manifest_is_valid_and_disabled(self) -> None:
        self.assertEqual(validate_infrastructure.validate_toolchain_manifest(), [])

    def test_toolchain_manifest_is_checked_against_committed_schema(self) -> None:
        manifest = {
            "schema_version": 1,
            "installation_enabled": False,
            "components": [
                {
                    "id": "example-tool",
                    "version": "1.0.0",
                    "source_url": "https://example.invalid/tool.tar.xz",
                    "sha256": "0" * 64,
                    "install_subdir": "example-tool/1.0.0",
                }
            ],
            "board_profiles": [],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "toolchains.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            errors = validate_infrastructure.validate_toolchain_manifest(path=path)

        self.assertTrue(any("platforms" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
