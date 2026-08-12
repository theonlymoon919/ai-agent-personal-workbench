import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ReleaseMetadataTests(unittest.TestCase):
    def test_public_version_metadata_stays_in_sync(self) -> None:
        frontend_version = json.loads(
            (ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
        )["version"]
        package_lock_version = json.loads(
            (ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8")
        )["version"]
        backend_source = (ROOT / "backend" / "app" / "version.py").read_text(encoding="utf-8")
        android_source = (ROOT / "mobile" / "app" / "build.gradle").read_text(encoding="utf-8")
        deployment = (ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

        backend_version = re.search(r'CLOUD_APP_VERSION = "([^"]+)"', backend_source).group(1)
        android_version = re.search(r"versionName '([^']+)'", android_source).group(1)

        self.assertRegex(frontend_version, r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
        self.assertEqual(package_lock_version, frontend_version)
        self.assertEqual(backend_version, frontend_version)
        self.assertEqual(android_version, frontend_version)
        self.assertIn(f"WORKBENCH_IMAGE_TAG={frontend_version}", deployment)
        self.assertIn(f"## [{frontend_version}]", changelog)


if __name__ == "__main__":
    unittest.main()
