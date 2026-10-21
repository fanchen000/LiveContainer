//
//  SideStore.swift
//  SideStoreSupport
//
//  Created by s s on 2025/7/20.
//

import Foundation
import AppIntents
import UserNotifications

@available(iOS 17.0, *)
func performIntentRefresh(identifier: String, mangledTypeName: String, intentProgress: Progress) async throws {
    // LC_REFRESH_INTENT_TO_HOST_SCHEDULER_V1: a host shortcut requests work from
    // the host scheduler. Only the scheduler launches the SideStore refresh engine.
    _ = intentProgress
    if UserDefaults.isSideStore() {
        try await SideStoreIntentCaller.shared.callRefreshIntent(mangledTypeName: mangledTypeName)
        return
    }
    try Task.checkCancellation()
    let request = V3ShortcutRefreshRequest.make()
    NotificationCenter.default.post(
        name: Notification.Name("LiveContainerAutoRefreshRunNow"),
        object: nil, userInfo: request.userInfo)
}

@available(iOS 17.0, *)
public struct RefreshAllAppsWidgetIntent: AppIntent, ProgressReportingIntent
{
    public static var title: LocalizedStringResource { "Refresh Apps via Widget" }
    // LC_REFRESH_HOST_INTENT_FOREGROUND_V1: widget requests must execute in the host app.
    public static var openAppWhenRun = true
    public static var isDiscoverable: Bool { false } // Don't show in Shortcuts or Spotlight.
    
    public init() {}
    
    public func perform() async throws -> some IntentResult
    {
        try await performIntentRefresh(identifier: "RefreshAllAppsWidgetIntent", mangledTypeName: "9SideStore26RefreshAllAppsWidgetIntentV", intentProgress: progress)
        return .result(dialog: "Refresh All was requested in LiveContainer. Check Refresh History for the run result.")
    }
}

@available(iOS 17.0, *)
public struct RefreshAllAppsIntent: AppIntent, CustomIntentMigratedAppIntent, PredictableIntent, ProgressReportingIntent, ForegroundContinuableIntent
{
    public static let intentClassName = "RefreshAllIntent"
    
    public static var title: LocalizedStringResource = "Refresh All Apps"
    public static var openAppWhenRun = true
    public static var description = IntentDescription("Refreshes your sideloaded apps to prevent them from expiring.")
    
    public init() {}
    
    public static var parameterSummary: some ParameterSummary {
        Summary("Refresh All Apps")
    }
    
    public static var predictionConfiguration: some IntentPredictionConfiguration {
        IntentPrediction {
            DisplayRepresentation(
                title: "Refresh All Apps",
                subtitle: ""
            )
        }
    }
    
    public func perform() async throws -> some IntentResult & ProvidesDialog
    {
        try await performIntentRefresh(identifier: "RefreshAllIntent", mangledTypeName: "9SideStore20RefreshAllAppsIntentV", intentProgress: progress)
        return .result(dialog: "Refresh All was requested in LiveContainer. Check Refresh History for the run result.")
    }
    
}


// LC_REFRESH_BRIDGE_V3_BEGIN
/// Dispatch the canonical SideStore guest refresh intent from the host scheduler.
public enum LiveContainerRefreshBridge {
    public static func refreshAllApps(runID: UUID) async throws {
        guard #available(iOS 17.0, *) else {
            throw NSError(domain: "LiveContainerRefresh.UnsupportedOS", code: 17,
                userInfo: [NSLocalizedDescriptionKey: "The embedded automatic refresh bridge requires iOS 17 or later."])
        }
        try Task.checkCancellation()
        try await RefreshHandler.shared.startScheduledRefresh(
            identifier: "RefreshAllIntent",
            mangledName: "9SideStore20RefreshAllAppsIntentV",
            runID: runID.uuidString
        )
        try Task.checkCancellation()
    }
}
// LC_REFRESH_BRIDGE_V3_END

class RefreshHandler: NSObject, RefreshServer {
    var c: UnsafeContinuation<(), any Error>? = nil
    var launchContinuation: UnsafeContinuation<(), any Error>? = nil
    var progress: Progress? = nil
    var listener: NSXPCListener? = nil
    var sideStorePid: Int32 = 0
    var client: RefreshClient? = nil
    var ext: NSExtension? = nil
    
    static var shared = RefreshHandler()
    
    func startRefresh(identifier: String, mangledName: String) async throws {
        if sideStorePid <= 0 || getpgid(sideStorePid) <= 0, let c {
            c.resume(throwing: NSError(domain: "SideStore", code: 1, userInfo: [NSLocalizedDescriptionKey: "Built-in SideStore quit unexpectedly"]))
            self.c = nil
        }
        
        if c != nil {
            throw NSError(domain: "SideStore", code: 1, userInfo: [NSLocalizedDescriptionKey: "Another refresh task is in progress."])
        }
        
        if listener == nil {
            guard let listener = startAnonymousListener(self) else {
                throw NSError(domain: "LiveContainerRefresh.XPC", code: 1, userInfo: [NSLocalizedDescriptionKey: "Unable to create the embedded SideStore XPC listener."])
            }
            self.listener = listener
        }
        guard let listener = self.listener else {
            throw NSError(domain: "LiveContainerRefresh.XPC", code: 2, userInfo: [NSLocalizedDescriptionKey: "Embedded SideStore XPC listener is unavailable."])
        }

        // launch SideStore if it's not running
        if (sideStorePid <= 0 || getpgid(sideStorePid) <= 0) && launchContinuation == nil {
            let lcHome = String(cString:getenv("LC_HOME_PATH"))
            let sideStoreHomeURL = URL(fileURLWithPath: lcHome).appendingPathComponent("Documents/SideStore")
            let bookmarkData = bookmarkForURL(sideStoreHomeURL)!

            // start LiveProcess
            let extensionItem = NSExtensionItem()
            extensionItem.userInfo = [
                "selected": "builtinSideStore",
                "bookmarks": [bookmarkData],
                "endpoint": listener.endpoint
            ]

            guard let liveProcessURL = UserDefaults.lcMainBundle().builtInPlugInsURL?.appendingPathComponent("LiveProcess.appex"),
                  let liveProcessBundle = Bundle(url: liveProcessURL)
            else {
                NSLog("Unable to locate LiveProcess bundle")
                throw NSError(domain: "SideStore", code: 1, userInfo: [NSLocalizedDescriptionKey: "Unable to locate LiveProcess bundle. To use the Refresh All Apps shortcut, reinstall LiveContainer+SideStore with LiveProcess installed. If you use SideStore, choose \"Keep App Extensions (Use Main Profile)\". If you use PlumeImpactor, choose \"Only Register Main Bundle\". For other sideloaders, select keep all extensions, i.e. DO NOT Remove any extension."])
            }
            
            var ext : NSExtension?
            do {
                ext = try NSExtension(identifier: liveProcessBundle.bundleIdentifier)
            } catch {
                NSLog("Failed to start extension \(error)")
                throw NSError(domain: "SideStore", code: 1, userInfo: [NSLocalizedDescriptionKey: "Failed to start extension \(error). To use the Refresh All Apps shortcut, reinstall LiveContainer+SideStore with LiveProcess installed. If you use SideStore, choose \"Keep App Extensions (Use Main Profile)\". If you use Impactor, choose \"Only Register Main Bundle\". For other sideloaders, select keep all extensions, i.e. DO NOT Remove any extension."])
            }
            guard let ext else {
                throw NSError(domain: "LiveContainerRefresh.XPC", code: 3, userInfo: [NSLocalizedDescriptionKey: "LiveProcess could not be created."])
            }
            self.ext = ext
            
            ext.setRequestInterruptionBlock { uuid in
                self.c?.resume(throwing: NSError(domain: "SideStore", code: 1, userInfo: [NSLocalizedDescriptionKey: "Built-in SideStore quit unexpectedly"]))
                self.c = nil
                self.sideStorePid = 0
                self.launchContinuation = nil
            }
            
            let uuid = await ext.beginRequest(withInputItems: [extensionItem])
            sideStorePid = ext.pid(forRequestIdentifier: uuid)
            
            try await withUnsafeThrowingContinuation { c in
                self.launchContinuation = c
                DispatchQueue.main.asyncAfter(deadline: .now() + 300) {
                    if let c = self.launchContinuation {
                        c.resume(throwing: NSError(domain: "SideStore", code: 1, userInfo: [NSLocalizedDescriptionKey: "Built-in SideStore failed to start in reasonable time"]))
                        self.launchContinuation = nil
                        ext._kill(9)
                    }
                }
            }
        }
        guard let client = self.client else {
            throw NSError(domain: "LiveContainerRefresh.XPC", code: 4,
                userInfo: [NSLocalizedDescriptionKey: "Embedded SideStore did not establish its refresh connection."])
        }
        try await withUnsafeThrowingContinuation { c in
            self.c = c
            // Store the continuation BEFORE sending work to the remote process.
            client.refreshAllApps(withIdentifier: identifier, mangledTypeName: mangledName, refreshRunID: V3SharedAppGroup.sharedUserDefaults()?.string(forKey: "liveContainerAutoRefreshExpectedRunID"))
        }
        
    }
    
    func updateProgress(_ value: Double) {
        progress?.completedUnitCount = Int64(value*100)
    }
    

    // LC_REFRESH_RESULT_XPC_V1: accept only this outstanding host request.
    // V3_RUNTIME_SHARED_REFRESH_STORE_V1: the expected run ID, the verification
    // manifest and the host-handoff record are the host/service contract, so
    // they are read from the one runtime App Group the host published. A fixed
    // suite name silently reads a store the embedded service never writes.
    func finishRefresh(_ error: String?, runID: String, verification: Data?) {
        guard let defaults = V3SharedAppGroup.sharedUserDefaults() else {
            finish("LiveContainer could not open its refresh-state store. Refresh is unconfirmed.")
            return
        }
        guard c != nil, defaults.string(forKey: "liveContainerAutoRefreshExpectedRunID") == runID else {
            NSLog("[LIVE_CONTAINER_REFRESH] RESULT_REJECTED reason=stale_run")
            return
        }
        if let verification, verification.count <= 262144 {
            do {
                let object = try PropertyListSerialization.propertyList(from: verification, options: [], format: nil)
                guard let payload = object as? [String: Any],
                      let manifest = payload["liveContainerAutoRefreshVerification"] as? [String: Any],
                      manifest["run_id"] as? String == runID else {
                    finish(error ?? "SideStore returned results for a different refresh attempt. Open SideStore and check its refresh history.")
                    return
                }
                defaults.set(manifest, forKey: "liveContainerAutoRefreshVerification")
                if payload["liveContainerAutoRefreshHostHandoffRunID"] as? String == runID {
                    for key in ["liveContainerAutoRefreshHostHandoff", "liveContainerAutoRefreshHostHandoffRunID", "liveContainerAutoRefreshHostHandoffStartedAt", "liveContainerAutoRefreshHostPreviousExpiration"] {
                        if let value = payload[key] { defaults.set(value, forKey: key) }
                    }
                }
                NSLog("[LIVE_CONTAINER_REFRESH] RESULT_RECEIVED run_id=%@", runID)
            } catch {
                finish("SideStore's installation results could not be read. Check its refresh history before retrying.")
                return
            }
        } else if error == nil {
            finish("SideStore returned no readable installation results. Refresh is unconfirmed; check embedded SideStore history.")
            return
        }
        finish(error)
    }

    func finish(_ error: String?) {
        if let error {
            c?.resume(throwing: NSError(domain: "SideStore", code: 1, userInfo: [NSLocalizedDescriptionKey: error]))
            c = nil
        } else {
            c?.resume()
            c = nil
        }
    }
    
    func onConnection(_ connection: NSXPCConnection!) {
        connection.remoteObjectInterface = NSXPCInterface(with: RefreshClient.self)
        client = connection.remoteObjectProxy as? RefreshClient
    }
    
    func finishedLaunching() {
        launchContinuation?.resume()
        launchContinuation = nil
    }

    func add(_ request: UNNotificationRequest) {
        UNUserNotificationCenter.current().add(request) { error in
            if let error {
                NSLog("Failed to add SideStore notification: \(error)")
            }
        }
    }

    func removePendingNotificationRequests(withIdentifiers identifiers: [String]) {
        UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: identifiers)
    }
    
}
