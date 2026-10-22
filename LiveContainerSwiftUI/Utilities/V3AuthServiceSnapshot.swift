import Foundation

public struct V3AuthServiceSnapshot: Equatable {
    public let authenticated: Bool
    public let credentialRoutePresent: Bool
    public let provisioningIncomplete: Bool
    public let provisioningRetryAvailable: Bool
    public let authenticationActive: Bool
    public let authenticationSessionID: String?
    public let identityStamp: String?
    public let identityStable: Bool

    public init(authenticated: Bool, provisioningIncomplete: Bool,
                provisioningRetryAvailable: Bool, authenticationActive: Bool,
                authenticationSessionID: String?, credentialRoutePresent: Bool = false,
                identityStamp: String? = nil, identityStable: Bool = true) {
        self.authenticated = authenticated
        self.credentialRoutePresent = credentialRoutePresent
        self.provisioningIncomplete = provisioningIncomplete
        self.provisioningRetryAvailable = provisioningRetryAvailable
        self.authenticationActive = authenticationActive
        self.authenticationSessionID = authenticationSessionID
        self.identityStamp = identityStamp
        self.identityStable = identityStable
    }
}
