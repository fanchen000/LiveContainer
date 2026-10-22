"""Synthetic, self-contained tests for the offline upgrade safety gate."""
import plistlib
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_upgrade_parity import audit, EXTENSIONS, HOST


def create_ipa(path, *, build="381111", group="group.com.SideStore.SideStore",
               guest_extension=None, side_version="0.7.0",
               scheme="livecontainer"):
    host = {
        "CFBundleIdentifier": "com.kdt.livecontainer",
        "CFBundleShortVersionString": "3.8.11",
        "CFBundleVersion": build,
        "CFBundleExecutable": "LiveContainer",
        "ALTAppGroups": [group],
        "CFBundleURLTypes": [{"CFBundleURLSchemes": [scheme]}],
        "UIApplicationSceneManifest": {"UIApplicationSupportsMultipleScenes": True},
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(HOST + "Info.plist", plistlib.dumps(host))
        z.writestr(HOST + "Frameworks/SideStoreApp.framework/Info.plist",
                   plistlib.dumps({"CFBundleShortVersionString": side_version}))
        for name in EXTENSIONS:
            bid = ("com.kdt.livecontainer." + name
                   if name != "LiveWidgetExtension" else "com.kdt.livecontainer.LiveWidget")
            if name == guest_extension:
                bid = "invalid.changed.identifier"
            z.writestr(HOST + "PlugIns/" + name + ".appex/Info.plist",
                       plistlib.dumps({"CFBundleIdentifier": bid,
                                        "NSExtension": {"NSExtensionPointIdentifier": "test.extension"}}))


class UpgradeParityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.before = self.root / "before.ipa"
        self.after = self.root / "after.ipa"
        create_ipa(self.before)

    def tearDown(self):
        self.tmp.cleanup()

    def result(self, **kwargs):
        create_ipa(self.after, **kwargs)
        return audit(self.before, self.after)

    def test_known_compatible_candidate(self):
        r = self.result(build="381112", side_version="0.7.0-20261017.511+abcdef")
        self.assertEqual(r["status"], "OFFLINE_UPGRADE_PARITY_PASS")
        self.assertTrue(r["embedded_sidestore_build_metadata_changed"])
        self.assertFalse(r["signed_update_approval"])

    def test_downgrade_is_blocked(self):
        self.assertIn("BUILD_VERSION_NOT_MONOTONIC",
                      self.result(build="3.8.11")["blockers"])

    def test_same_build_not_an_upgrade(self):
        self.assertIn("BUILD_VERSION_NOT_MONOTONIC",
                      self.result(build="381111")["blockers"])

    def test_appgroup_change_is_blocked(self):
        self.assertIn("HOST_OR_EXTENSION_IDENTITY_DRIFT",
                      self.result(build="381112", group="group.other")["blockers"])

    def test_url_scheme_change_is_blocked(self):
        self.assertIn("HOST_OR_EXTENSION_IDENTITY_DRIFT",
                      self.result(build="381112", scheme="changed")["blockers"])

    def test_extension_replacement_is_blocked(self):
        self.assertIn("HOST_OR_EXTENSION_IDENTITY_DRIFT",
                      self.result(build="381112",
                                  guest_extension="LiveProcess")["blockers"])

    def test_major_sidestore_change_is_blocked(self):
        self.assertIn("EMBEDDED_SIDESTORE_RELEASE_LINE_DRIFT",
                      self.result(build="381112", side_version="0.6.4")["blockers"])

    def test_corrupt_candidate_is_blocked(self):
        self.after.write_bytes(b"not a zip")
        self.assertEqual(audit(self.before, self.after)["status"],
                         "BLOCKED_OFFLINE_UPGRADE_PARITY")


if __name__ == "__main__":
    unittest.main()
