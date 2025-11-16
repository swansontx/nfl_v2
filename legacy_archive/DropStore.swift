import Foundation
import CoreLocation
import Combine
import FirebaseAuth
import FirebaseFirestore

@MainActor
final class DropStore: ObservableObject {
    private let db = Firestore.firestore()

    // Published state for UI
    @Published var currentUser: User? = nil
    @Published var isUsingAnonymousAccount: Bool = true
    @Published var authError: String? = nil
    @Published var drops: [DropItem] = []
    @Published var lifted: Set<String> = []

    // Listener management
    private var listeners: [ListenerRegistration] = []
    private var authListener: AuthStateDidChangeListenerHandle?

    // Local caches
    private var remoteDrops: [String: DropItem] = [:]
    private var optimisticDrops: [String: DropItem] = [:]

    // Debounce helper for viewport changes
    private var debounceWorkItem: DispatchWorkItem?
    private let debounceInterval: TimeInterval = 0.35

    init() {
        authListener = Auth.auth().addStateDidChangeListener { [weak self] _, user in
            guard let self = self else { return }
            self.updateCurrentUser(with: user)
        }
        ensureSignedIn()
    }

    deinit {
        if let authListener = authListener {
            Auth.auth().removeStateDidChangeListener(authListener)
        }
        stopListeningNearby()
    }

    // MARK: - Authentication Handling

    /// Ensures there's a Firebase Auth user (Apple or anonymous)
    func ensureSignedIn() {
        if Auth.auth().currentUser == nil {
            Auth.auth().signInAnonymously { [weak self] result, error in
                guard let self = self else { return }
                if let error {
                    print("Anonymous sign-in failed:", error.localizedDescription)
                    self.authError = error.localizedDescription
                    self.updateCurrentUser(with: nil)
                } else if let user = result?.user {
                    print("Signed in anonymously as \(user.uid)")
                    self.authError = nil
                    self.updateCurrentUser(with: user)
                }
            }
        } else {
            authError = nil
            updateCurrentUser(with: Auth.auth().currentUser)
        }
    }

    /// Signs the user out completely (forces re-auth next launch)
    func signOut() {
        do {
            try Auth.auth().signOut()
            // teardown listeners and caches
            stopListeningNearby()
            currentUser = nil
            drops.removeAll()
            optimisticDrops.removeAll()
            remoteDrops.removeAll()
            lifted.removeAll()
            isUsingAnonymousAccount = true
            authError = nil
        } catch {
            print("Error signing out:", error.localizedDescription)
            authError = error.localizedDescription
        }
        // keep app usable by ensuring anonymous sign-in
        ensureSignedIn()
    }

    func signInWithApple(idToken: String, nonce: String, fullName: PersonNameComponents?) {
        let credential = OAuthProvider.appleCredential(
            withIDToken: idToken,
            rawNonce: nonce,
            fullName: fullName
        )

        let auth = Auth.auth()
        let finish: (AuthDataResult?, Error?) -> Void = { [weak self] result, error in
            guard let self = self else { return }

            if let error {
                print("Sign in failed:", error.localizedDescription)
                self.authError = error.localizedDescription
                return
            }

            if let user = result?.user ?? auth.currentUser {
                self.authError = nil
                self.applyDisplayNameIfNeeded(fullName, to: user)
                self.updateCurrentUser(with: user)
            }
        }

        if let current = auth.currentUser, current.isAnonymous {
            current.link(with: credential) { result, error in
                if let error = error as NSError?,
                   error.code == AuthErrorCode.credentialAlreadyInUse.rawValue {
                    auth.signIn(with: credential) { result, error in
                        if error == nil {
                            // remove the old anonymous account to avoid orphan
                            current.delete(completion: nil)
                        }
                        finish(result, error)
                    }
                } else {
                    finish(result, error)
                }
            }
        } else {
            auth.signIn(with: credential, completion: finish)
        }
    }

    private func updateCurrentUser(with authUser: FirebaseAuth.User?) {
        guard let authUser else {
            currentUser = nil
            isUsingAnonymousAccount = true
            return
        }

        isUsingAnonymousAccount = authUser.isAnonymous
        let displayName = authUser.displayName?.trimmingCharacters(in: .whitespacesAndNewlines)
        currentUser = User(id: authUser.uid,
                           name: (displayName?.isEmpty == false ? displayName! : "Guest"))
    }

    private func applyDisplayNameIfNeeded(_ fullName: PersonNameComponents?,
                                          to user: FirebaseAuth.User) {
        guard let fullName else { return }

        let formatter = PersonNameComponentsFormatter()
        let displayName = formatter.string(from: fullName)
            .trimmingCharacters(in: .whitespacesAndNewlines)

        guard !displayName.isEmpty, user.displayName != displayName else { return }

        let changeRequest = user.createProfileChangeRequest()
        changeRequest.displayName = displayName
        changeRequest.commitChanges { [weak self] error in
            if let error {
                print("Failed to update display name:", error.localizedDescription)
                self?.authError = error.localizedDescription
            } else {
                self?.authError = nil
                self?.updateCurrentUser(with: user)
            }
        }
    }

    // MARK: - Drop Creation

    func createDrop(text: String,
                    visibility: DropVisibility,
                    at coordinate: CLLocationCoordinate2D) {
        guard let user = Auth.auth().currentUser else {
            print("User not signed in")
            return
        }

        let createdAt = Date()
        let docRef = db.collection("drops").document()
        let dropId = docRef.documentID
        let author = currentUser ?? User(id: user.uid, name: user.displayName ?? "You")

        var optimistic = DropItem(
            id: dropId,
            text: text.trimmingCharacters(in: .whitespacesAndNewlines),
            author: author,
            createdAt: createdAt,
            coordinate: coordinate,
            visibility: visibility,
            reactions: 0,
            isLiftedByCurrentUser: false,
            syncStatus: .pending
        )

        optimisticDrops[dropId] = optimistic
        publishDrops()

        let payload = dropPayload(for: optimistic, authorId: user.uid)

        docRef.setData(payload) { [weak self] error in
            guard let self = self else { return }
            Task { @MainActor in
                if let error = error {
                    print("Error creating drop:", error.localizedDescription)
                    optimistic.syncStatus = .failed(message: error.localizedDescription)
                    self.optimisticDrops[dropId] = optimistic
                } else {
                    optimistic.syncStatus = .synced
                    self.optimisticDrops[dropId] = optimistic
                    print("✅ Drop created successfully")
                }
                self.publishDrops()
            }
        }
    }

    func retryCreate(drop: DropItem) {
        guard case .failed = drop.syncStatus else { return }
        guard let user = Auth.auth().currentUser else {
            print("User not signed in")
            return
        }

        var retryDrop = drop
        retryDrop.author = User(id: user.uid, name: user.displayName ?? drop.author.name)
        retryDrop.createdAt = Date()
        retryDrop.syncStatus = .pending
        optimisticDrops[drop.id] = retryDrop
        publishDrops()

        let payload = dropPayload(for: retryDrop, authorId: user.uid)
        let docRef = db.collection("drops").document(drop.id)

        docRef.setData(payload) { [weak self] error in
            guard let self = self else { return }
            Task { @MainActor in
                if let error = error {
                    print("Retry failed:", error.localizedDescription)
                    retryDrop.syncStatus = .failed(message: error.localizedDescription)
                    self.optimisticDrops[drop.id] = retryDrop
                } else {
                    retryDrop.syncStatus = .synced
                    self.optimisticDrops[drop.id] = retryDrop
                    print("✅ Drop retried successfully")
                }
                self.publishDrops()
            }
        }
    }

    // MARK: - Nearby Fetch / Realtime Listener

    /// Debounced public API — call from UI when viewport/center changes
    func scheduleListenNearby(minLat: Double, maxLat: Double, minLon: Double, maxLon: Double) {
        debounceWorkItem?.cancel()
        let wi = DispatchWorkItem { [weak self] in
            self?.listenNearby(minLat: minLat, maxLat: maxLat, minLon: minLon, maxLon: maxLon)
        }
        debounceWorkItem = wi
        DispatchQueue.main.asyncAfter(deadline: .now() + debounceInterval, execute: wi)
    }

    func listenNearby(minLat: Double, maxLat: Double, minLon: Double, maxLon: Double) {
        // teardown existing listeners
        stopListeningNearby()
        remoteDrops.removeAll()

        // guard max radius (simple heuristic)
        let latSpan = maxLat - minLat
        let lonSpan = maxLon - minLon
        let approxMeters = max(abs(latSpan) * 111000.0, abs(lonSpan) * 111000.0)
        if approxMeters > 50000 { // cap at 50km for safety
            print("Viewport too large — not starting listeners")
            return
        }

        let prefixes = Geohash.prefixesCovering(
            region: (minLat, maxLat, minLon, maxLon),
            precision: 5
        )

        for prefix in prefixes {
            let start = prefix
            let end = prefix + "\u{f8ff}"

            let registration = db.collection("drops")
                .order(by: "geohash")
                .start(at: [start])
                .end(at: [end])
                .limit(to: 200)
                .addSnapshotListener { [weak self] snap, err in
                    guard let self = self else { return }

                    if let err = err {
                        print("Firestore listener error:", err.localizedDescription)
                        return
                    }

                    guard let snap else { return }

                    for change in snap.documentChanges {
                        let doc = change.document
                        let data = doc.data()
                        guard
                            let text = data["text"] as? String,
                            let vis = data["visibility"] as? String,
                            let geo = data["location"] as? GeoPoint
                        else { continue }

                        let item = DropItem(
                            id: doc.documentID,
                            text: text,
                            author: User(id: data["authorId"] as? String ?? "unknown",
                                         name: "Unknown"),
                            createdAt: (data["createdAt"] as? Timestamp)?.dateValue() ?? .now,
                            coordinate: CLLocationCoordinate2D(latitude: geo.latitude,
                                                               longitude: geo.longitude),
                            visibility: DropVisibility(rawValue: vis) ?? .public,
                            reactions: 0,
                            isLiftedByCurrentUser: lifted.contains(doc.documentID),
                            syncStatus: .synced
                        )

                        switch change.type {
                        case .added, .modified:
                            self.remoteDrops[item.id] = item
                        case .removed:
                            self.remoteDrops.removeValue(forKey: item.id)
                        @unknown default:
                            break
                        }
                    }

                    self.publishDrops()
                }
            listeners.append(registration)
        }
    }

    /// Stop and remove all listeners
    func stopListeningNearby() {
        listeners.forEach { $0.remove() }
        listeners.removeAll()
    }

    // MARK: - Reactions & Lifts (Local Only for Now)

    func toggleLift(_ drop: DropItem) {
        if lifted.contains(drop.id) {
            lifted.remove(drop.id)
        } else {
            lifted.insert(drop.id)
        }
        if let i = drops.firstIndex(where: { $0.id == drop.id }) {
            drops[i].isLiftedByCurrentUser = lifted.contains(drop.id)
        }
        if var remote = remoteDrops[drop.id] {
            remote.isLiftedByCurrentUser = lifted.contains(drop.id)
            remoteDrops[drop.id] = remote
        }
        if var optimistic = optimisticDrops[drop.id] {
            optimistic.isLiftedByCurrentUser = lifted.contains(drop.id)
            optimisticDrops[drop.id] = optimistic
        }
        publishDrops()
    }

    func react(to drop: DropItem) {
        if let i = drops.firstIndex(where: { $0.id == drop.id }) {
            drops[i].reactions += 1
        }
        if var remote = remoteDrops[drop.id] {
            remote.reactions += 1
            remoteDrops[drop.id] = remote
        }
        if var optimistic = optimisticDrops[drop.id] {
            optimistic.reactions += 1
            optimisticDrops[drop.id] = optimistic
        }
        publishDrops()
    }

    // MARK: - Helpers

    private func publishDrops() {
        let syncedIds = optimisticDrops.compactMap { id, drop -> String? in
            if remoteDrops[id] != nil, drop.syncStatus == .synced {
                return id
            }
            return nil
        }
        syncedIds.forEach { optimisticDrops.removeValue(forKey: $0) }

        var combined = Array(remoteDrops.values)
        combined.append(contentsOf: optimisticDrops.values)
        combined.sort(by: { $0.createdAt > $1.createdAt })
        drops = combined
    }

    private func dropPayload(for drop: DropItem, authorId: String) -> [String: Any] {
        let geohash = Geohash.encode(latitude: drop.coordinate.latitude,
                                     longitude: drop.coordinate.longitude,
                                     precision: 7)

        return [
            "text": drop.text,
            "authorId": authorId,
            "createdAt": Timestamp(date: drop.createdAt),
            "visibility": drop.visibility.rawValue,
            "location": GeoPoint(latitude: drop.coordinate.latitude,
                                  longitude: drop.coordinate.longitude),
            "geohash": geohash
        ]
    }
}
