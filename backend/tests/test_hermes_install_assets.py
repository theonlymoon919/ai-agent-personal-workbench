from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.install_hermes_assets import MANAGED_START, install_assets
from scripts.hermes_cloud_connector import websocket_url
from scripts.hermes_upload_health_image import public_result, workbench_origin


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class HermesAssetInstallerTests(unittest.TestCase):
    def test_windows_runtime_powershell_scripts_are_ascii_for_powershell_five(self) -> None:
        for name in (
            "install_hermes_workbench.ps1",
            "start_hermes_cloud_connector.ps1",
            "upload_health_image.ps1",
        ):
            script = PROJECT_ROOT / "scripts" / name
            try:
                script.read_bytes().decode("utf-8-sig").encode("ascii")
            except UnicodeError as exc:
                self.fail(f"{name} must remain ASCII-compatible for Windows PowerShell 5: {exc}")

    def test_public_installer_requires_an_explicit_generic_https_origin(self) -> None:
        installer = (PROJECT_ROOT / "scripts" / "install_hermes_workbench.ps1").read_text(
            encoding="ascii"
        )
        starter = (PROJECT_ROOT / "scripts" / "start_hermes_cloud_connector.ps1").read_text(
            encoding="ascii"
        )
        self.assertIn("$env:PERSONAL_WORKBENCH_URL", installer)
        self.assertIn("https://workbench.example.com", installer)
        self.assertNotIn("sslip.io", installer + starter)
        self.assertNotIn("127.0.0.1:8787", installer + starter)

    def test_installs_current_skill_removes_legacy_and_preserves_soul(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            hermes_home = Path(temporary_directory) / "hermes"
            legacy = (
                hermes_home
                / "skills"
                / "software-development"
                / "personal-workbench-app"
            )
            legacy.mkdir(parents=True)
            (legacy / "SKILL.md").write_text(
                "legacy plaintext credential that must be removed",
                encoding="utf-8",
            )
            soul = hermes_home / "SOUL.md"
            soul.write_text("# Existing identity\n\nKeep this line.\n", encoding="utf-8")

            arguments = {
                "hermes_home": hermes_home,
                "source_skill_root": PROJECT_ROOT / "hermes" / "personal-workbench",
                "operating_rules_path": PROJECT_ROOT / "docs" / "HERMES_WORKBENCH_PROMPT.md",
                "configure_image_handoff": False,
            }
            first = install_assets(**arguments)
            second = install_assets(**arguments)

            installed = (
                hermes_home / "skills" / "productivity" / "personal-workbench"
            )
            soul_text = soul.read_text(encoding="utf-8")
            self.assertTrue(first["legacy_skill_removed"])
            self.assertFalse(second["legacy_skill_removed"])
            self.assertFalse(legacy.exists())
            self.assertTrue((installed / "SKILL.md").is_file())
            self.assertTrue((installed / "references" / "operating-rules.md").is_file())
            skill_text = (installed / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("delete_finance_transaction", skill_text)
            self.assertIn("confirmed=true", skill_text)
            self.assertIn("delete_weight_entry", skill_text)
            self.assertIn("独立的演示账号", skill_text)
            self.assertIn("Keep this line.", soul_text)
            self.assertEqual(soul_text.count(MANAGED_START), 1)
            self.assertNotIn("plaintext credential", soul_text)

    def test_requires_existing_connection_without_reading_or_printing_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            hermes_home = Path(temporary_directory) / "hermes"
            with self.assertRaisesRegex(RuntimeError, "没有检测到可复用"):
                install_assets(
                    hermes_home=hermes_home,
                    source_skill_root=PROJECT_ROOT / "hermes" / "personal-workbench",
                    operating_rules_path=PROJECT_ROOT / "docs" / "HERMES_WORKBENCH_PROMPT.md",
                    configure_image_handoff=False,
                    require_existing_connection=True,
                )

    def test_reuses_existing_connection_without_exposing_its_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            hermes_home = Path(temporary_directory) / "hermes"
            hermes_home.mkdir()
            (hermes_home / ".env").write_text(
                "MCP_PERSONAL_WORKBENCH_API_KEY=test-placeholder-not-a-credential\n",
                encoding="utf-8",
            )
            (hermes_home / "config.yaml").write_text(
                "mcp_servers:\n  personal_workbench:\n    url: https://workbench.example.com/mcp/\n",
                encoding="utf-8",
            )
            result = install_assets(
                hermes_home=hermes_home,
                source_skill_root=PROJECT_ROOT / "hermes" / "personal-workbench",
                operating_rules_path=PROJECT_ROOT / "docs" / "HERMES_WORKBENCH_PROMPT.md",
                configure_image_handoff=False,
                require_existing_connection=True,
            )
            self.assertTrue(result["ok"])
            self.assertNotIn("token", result)

    def test_health_bridge_requires_a_record_id_before_reporting_success(self) -> None:
        with self.assertRaisesRegex(ValueError, "identifier"):
            public_result({"kind": "exercise"})
        self.assertEqual(
            public_result({"id": "record-123", "kind": "exercise"})["record_id"],
            "record-123",
        )

    def test_bridge_and_connector_reject_non_origin_urls(self) -> None:
        for invalid in (
            "https://workbench.example.com/private",
            "https://workbench.example.com?token=example",
            "https://user:password@workbench.example.com",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    workbench_origin(invalid)
                with self.assertRaises(ValueError):
                    websocket_url(invalid)

        self.assertEqual(
            workbench_origin("https://workbench.example.com/"),
            "https://workbench.example.com",
        )
        self.assertEqual(
            websocket_url("https://workbench.example.com/"),
            "wss://workbench.example.com/ws/agent",
        )


if __name__ == "__main__":
    unittest.main()
