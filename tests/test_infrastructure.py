from __future__ import annotations

from pathlib import Path
import sys
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


if __name__ == "__main__":
    unittest.main()
