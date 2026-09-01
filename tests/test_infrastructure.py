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

    def test_camera_validation_setup_is_package_only(self) -> None:
        self.assertEqual(
            validate_infrastructure.validate_camera_validation_package_boundary(), []
        )

    def test_camera_reference_boundary_contains_no_device_implementation(self) -> None:
        self.assertEqual(validate_infrastructure.validate_camera_reference_boundary(), [])

    def test_remote_ci_is_outbound_private_and_not_an_ephy_worker_job(self) -> None:
        self.assertEqual(validate_infrastructure.validate_remote_ci_boundary(), [])

    def test_network_mtu_is_explicit_and_outside_the_safe_baseline(self) -> None:
        self.assertEqual(validate_infrastructure.validate_network_mtu_boundary(), [])

    def test_camera_ci_exports_media_only_on_explicit_private_request(self) -> None:
        workflow = (
            ROOT
            / "examples"
            / "control-repository"
            / ".github"
            / "workflows"
            / "physical-ci-camera-capture.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("secrets.PHYSICAL_CI_SERIAL_DEVICE", workflow)
        self.assertIn("validate-camera-artifacts", workflow)
        self.assertIn("retrieve_image:", workflow)
        self.assertIn("default: false", workflow)
        self.assertIn("if: ${{ inputs.retrieve_image }}", workflow)
        self.assertRegex(workflow, r"actions/upload-artifact@[a-f0-9]{40}")
        self.assertIn("retention-days: 1", workflow)
        self.assertNotIn("run-camera-reference flash", workflow)

    def test_udev_preserves_builtin_stable_links(self) -> None:
        self.assertEqual(validate_infrastructure.validate_udev_boundary(), [])

    def test_toolchain_manifest_is_valid_and_disabled(self) -> None:
        self.assertEqual(validate_infrastructure.validate_toolchain_manifest(), [])

    def test_espressif_profile_names_the_physical_board(self) -> None:
        manifest = json.loads(
            (ROOT / "manifests" / "toolchains.json").read_text(encoding="utf-8")
        )
        profile_ids = {profile["id"] for profile in manifest["board_profiles"]}
        self.assertIn("xiao-esp32s3-sense", profile_ids)
        self.assertNotIn("xiao-espressif", profile_ids)

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
