#!/usr/bin/env python3
"""Offline V3 source/layout gate, independent of signing and developer accounts.

This is NOT a substitute for Xcode compile, signing, installation or on-device
refresh. Exits nonzero if the package's scheduler contracts have drifted.
"""
from pathlib import Path
import plistlib
import sys

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "LiveContainerSwiftUI" / "App" / "AppDelegate.swift"
SETTINGS = ROOT / "LiveContainerSwiftUI" / "Views" / "Settings" / "LCSettingsView.swift"
SOURCES = [
    "LiveContainerSwiftUI/App/LiveContainerAutoRefreshAlarm.swift",
    "SideStoreSupport/V3SharedAppGroup.swift",
    "LiveContainerSwiftUI/Views/Settings/LCEmbeddedSideStoreRefreshView.swift",
]
errors = []


def require(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


with (ROOT / "LiveContainer" / "Info.plist").open("rb") as f:
    info = plistlib.load(f)
ids = info.get("BGTaskSchedulerPermittedIdentifiers", [])
ids = ids if isinstance(ids, list) else []
processing = [v for v in ids if isinstance(v, str)
              and v.endswith(".sidestore.automatic-refresh")]
require(len(processing) == 1 and len(ids) == len(set(ids)),
        "missing/ambiguous processing task ID")
require(len(processing) == 1 and processing[0] + ".watchdog" in ids,
        "watchdog ID missing")
modes = info.get("UIBackgroundModes", [])
require(isinstance(modes, list) and {"processing", "fetch"}.issubset(set(modes)),
        "processing/fetch background mode missing")
for f in SOURCES:
    require((ROOT / f).is_file(), "source not tracked: " + f)
swift = APP.read_text(encoding="utf-8")
for symbol in (
    "LiveContainerAutoRefreshScheduler.register()",
    "LiveContainerAutoRefreshScheduler.schedule()",
    "LiveContainerAutoRefreshScheduler.recoverAfterLaunchOrResume()",
    'static let runLedgerKey = "liveContainerAutoRefreshRunLedger"',
    'static let healthStateKey = "liveContainerAutoRefreshHealthState"',
):
    require(symbol in swift, "missing runtime hook: " + symbol)
require("LiveContainerAutoRefreshScheduler" in SETTINGS.read_text(encoding="utf-8")
        or "LCEmbeddedSideStoreRefreshView" in SETTINGS.read_text(encoding="utf-8"),
        "settings entrypoint not connected")
pbx = (ROOT / "LiveContainer.xcodeproj" / "project.pbxproj").read_text(encoding="utf-8")
require("PBXFileSystemSynchronizedRootGroup" in pbx and
        "LiveContainerSwiftUI" in pbx, "Swift files not connected to Xcode target")
require("LiveProcess" in pbx, "LiveProcess target missing")
bridge = (ROOT / "SideStoreSupport" / "SideStore.swift").read_text(encoding="utf-8")
require("struct V3ShortcutRefreshRequest" in bridge and
        "func startScheduledRefresh(" in bridge,
        "SideStoreSupport scheduled refresh bridge not linked")
groups = (ROOT / "SideStoreSupport" / "V3SharedAppGroup.swift").read_text(encoding="utf-8")
require("public enum V3SharedAppGroup" in groups and
        "public enum V3SharedRefreshStore" in groups,
        "shared App Group implementation not exported from SideStoreSupport")

if errors:
    for item in errors:
        print("BLOCKED_SOURCE_GATE:", item)
    sys.exit(2)
print("V3_SOURCE_PREFLIGHT_PASS: declarations, runtime hooks, Swift target, LiveProcess")
print("NOT_VERIFIED: Xcode compile, signed IPA, installed-profile expiry, unattended execution")
