#!/usr/bin/env python3
"""Compare an offline, unsigned candidate against a preserved LiveContainer IPA.

This checks *packaging* continuity only. It cannot prove signed update
identity, keychain group continuity, preservation of installed Guest data, or
successful unattended operation on iOS. Those must pass on device.
"""
import argparse
import json
import plistlib
import zipfile
from pathlib import Path

HOST = "Payload/LiveContainer.app/"
EXTENSIONS = ("LiveProcess", "LiveWidgetExtension", "LaunchAppExtension",
              "ShareExtension")
IDENTITY_KEYS = (
    "CFBundleIdentifier", "CFBundleShortVersionString", "CFBundleExecutable",
    "CFBundleURLTypes", "ALTAppGroups", "UIApplicationSceneManifest",
    "UISupportedInterfaceOrientations", "NSAppTransportSecurity",
)


def inspect(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None:
            raise ValueError("archive CRC failed")
        host = plistlib.loads(z.read(HOST + "Info.plist"))
        ext = {}
        for name in EXTENSIONS:
            info = plistlib.loads(z.read(
                HOST + "PlugIns/" + name + ".appex/Info.plist"))
            ext[name] = {
                "bundle_id": info.get("CFBundleIdentifier"),
                "extension_point": (
                    info.get("NSExtension", {}).get("NSExtensionPointIdentifier")
                    if isinstance(info.get("NSExtension"), dict) else None
                ),
            }
        framework = plistlib.loads(z.read(
            HOST + "Frameworks/SideStoreApp.framework/Info.plist"))
        return {"host": host, "extensions": ext, "embedded_sidestore_version":
                framework.get("CFBundleShortVersionString"),
                "unsigned": HOST + "embedded.mobileprovision" not in z.namelist()}


def audit(old: Path, new: Path) -> dict:
    result = {
        "status": "BLOCKED_OFFLINE_UPGRADE_PARITY",
        "phone_modified": False,
        "guest_data_copied_or_deleted": False,
        "on_device_identity_attested": False,
        "on_device_guest_integrity_attested": False,
        "signed_update_approval": False,
    }
    try:
        before = inspect(old)
        after = inspect(new)
        diff = [k for k in IDENTITY_KEYS
                if before["host"].get(k) != after["host"].get(k)]
        for name in EXTENSIONS:
            if before["extensions"][name] != after["extensions"][name]:
                diff.append("extension:" + name)
        prior_build = before["host"].get("CFBundleVersion")
        new_build = after["host"].get("CFBundleVersion")
        try:
            monotonic = (str(prior_build).isdecimal() and str(new_build).isdecimal()
                         and int(new_build) > int(prior_build))
        except (ValueError, TypeError):
            monotonic = False
        prior_side = before["embedded_sidestore_version"]
        new_side = after["embedded_sidestore_version"]
        # 0.7.0 and 0.7.0-20261017.511+commit share a release line.
        # A pinned CI commit suffix is metadata, not a different major/minor
        # SideStore API. Still report the metadata change for review.
        side_release_compatible = (
            isinstance(prior_side, str) and isinstance(new_side, str)
            and prior_side.split("-", 1)[0] == new_side.split("-", 1)[0])
        metadata_changed = prior_side != new_side
        blockers = []
        if diff:
            blockers.append("HOST_OR_EXTENSION_IDENTITY_DRIFT")
        if not monotonic:
            blockers.append("BUILD_VERSION_NOT_MONOTONIC")
        if not side_release_compatible:
            blockers.append("EMBEDDED_SIDESTORE_RELEASE_LINE_DRIFT")
        if not after["unsigned"]:
            blockers.append("UNEXPECTED_BUNDLED_PROVISIONING_PROFILE")
        result.update({
            "status": "OFFLINE_UPGRADE_PARITY_PASS" if not blockers
                      else "BLOCKED_OFFLINE_UPGRADE_PARITY",
            "prior_build": prior_build, "candidate_build": new_build,
            "host_identity_keys_unchanged": not bool(diff),
            "different_keys": diff,
            "four_extension_identifiers_unchanged": not any(
                k.startswith("extension:") for k in diff),
            "embedded_sidestore_release_line_unchanged": side_release_compatible,
            "embedded_sidestore_build_metadata_changed": metadata_changed,
            "candidate_is_unsigned": after["unsigned"],
            "blockers": blockers,
            "final_install_gate": (
                "BLOCKED_UNTIL_SIGNED_IDENTITY_GROUPS_GUEST_BACKUP_AND_REAL_DEVICE_VERIFIED"),
        })
    except (OSError, KeyError, ValueError, TypeError, plistlib.InvalidFileException,
            zipfile.BadZipFile) as exc:
        result["blockers"] = ["INVALID_ARCHIVE_" + type(exc).__name__.upper()]
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("preserved_ipa", type=Path)
    ap.add_argument("candidate_ipa", type=Path)
    a = ap.parse_args()
    result = audit(a.preserved_ipa, a.candidate_ipa)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "OFFLINE_UPGRADE_PARITY_PASS" else 2)
