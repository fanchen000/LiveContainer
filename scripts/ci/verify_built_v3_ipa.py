"""Fail-closed OFFLINE gate for an iOS LiveContainer+SideStore auto-refresh IPA.

Never installs, signs, connects to the phone or reads account credentials.
The runtime must be compiled and BGTaskScheduler declarations must match its
resolver; changing Info.plist alone cannot substitute for compiled code.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import plistlib
import zipfile


def verify(path: Path) -> dict:
    result = {"status": "BLOCKED_V3_AUTOMATIC_REFRESH_WIRING",
              "phone_modified": False, "signing_attempted": False}
    try:
        with zipfile.ZipFile(path) as z:
            if z.testzip() is not None:
                result["blockers"] = ["ZIP_CRC_FAILURE"]
                return result
            base = "Payload/LiveContainer.app/"
            info = plistlib.loads(z.read(base + "Info.plist"))
            ids = info.get("BGTaskSchedulerPermittedIdentifiers")
            if not isinstance(ids, list) or not all(isinstance(v, str) for v in ids):
                ids = []
            candidates = [s for s in ids if isinstance(s, str)
                          and s.endswith(".sidestore.automatic-refresh")]
            modes = info.get("UIBackgroundModes")
            modes = set(modes) if isinstance(modes, list) else set()
            suffix_ok = len(candidates) == 1 and len(set(ids)) == len(ids)
            pair_ok = suffix_ok and candidates[0] + ".watchdog" in ids
            background_ok = "fetch" in modes and "processing" in modes
            plugins = {n.split("/PlugIns/")[-1].split(".appex/")[0]
                       for n in z.namelist()
                       if n.startswith(base) and "/PlugIns/" in n
                       and n.endswith(".appex/Info.plist")}
            required_extensions = {
                "LiveProcess", "LiveWidgetExtension",
                "LaunchAppExtension", "ShareExtension",
            }
            extension_ok = required_extensions.issubset(plugins)
            embedded_path = base + "Frameworks/SideStoreApp.framework/Info.plist"
            try:
                embedded_info = plistlib.loads(z.read(embedded_path))
                embedded_version = embedded_info.get("CFBundleShortVersionString")
                side_store_ok = isinstance(embedded_version, str) and embedded_version.startswith("0.7.")
            except (KeyError, ValueError, plistlib.InvalidFileException):
                side_store_ok = False
            markers = (
                b"liveContainerAutoRefreshRunLedger",
                b"liveContainerAutoRefreshLastSuccessfulRefresh",
                b"SideStore scheduled refresh",
            )
            discovered: set[bytes] = set()
            scanned = 0
            for member in z.infolist():
                name = member.filename
                if (not name.startswith(base) or member.file_size > 120_000_000 or
                    not (name.endswith("/LiveContainer") or
                         name.endswith("/LiveContainerSwiftUI") or
                         name.endswith(".dylib"))):
                    continue
                scanned += 1
                data = z.read(member)
                discovered.update(m for m in markers if m in data)
            runtime_ok = all(m in discovered for m in markers)
            blockers = []
            if not pair_ok:
                blockers.append("MISSING_OR_AMBIGUOUS_BG_TASK_IDENTIFIERS")
            if not background_ok:
                blockers.append("MISSING_PROCESSING_OR_FETCH_BACKGROUND_MODE")
            if not runtime_ok:
                blockers.append("V3_COMPILED_RUNTIME_NOT_ATTESTED")
            if not extension_ok:
                blockers.append("REQUIRED_HOST_EXTENSIONS_MISSING")
            if not side_store_ok:
                blockers.append("SIDESTORE_EMBEDDED_RUNTIME_MISSING_OR_UNEXPECTED")
            result.update({
                "status": "OFFLINE_V3_WIRING_PASS" if not blockers
                          else "BLOCKED_V3_AUTOMATIC_REFRESH_WIRING",
                "host_version": info.get("CFBundleShortVersionString"),
                "task_ids_pair_valid": pair_ok,
                "background_modes_valid": background_ok,
                "compiled_runtime_markers_found": len(discovered),
                "compiled_runtime_markers_required": len(markers),
                "binary_count_scanned": scanned,
                "required_extensions_present": extension_ok,
                "embedded_sidestore_present": side_store_ok,
                "blockers": blockers,
                "signed_identity_verified": False,
                "installed_on_phone_verified": False,
            })
    except (OSError, KeyError, ValueError, plistlib.InvalidFileException,
            zipfile.BadZipFile) as exc:
        result["blockers"] = ["INVALID_CANDIDATE_" + type(exc).__name__.upper()]
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ipa", type=Path)
    args = parser.parse_args()
    result = verify(args.ipa)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "OFFLINE_V3_WIRING_PASS" else 2)


if __name__ == "__main__":
    main()
