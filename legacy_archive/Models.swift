import Foundation
import CoreLocation

enum DropVisibility: String, CaseIterable, Identifiable {
    case `public` = "Public"
    case friends = "Friends"
    case `private` = "Private"
    var id: String { rawValue }
}

struct User: Identifiable, Hashable {
    let id: String
    var name: String
}

struct DropItem: Identifiable, Hashable {
    let id: String
    var text: String
    var author: User
    var createdAt: Date
    var coordinate: CLLocationCoordinate2D
    var visibility: DropVisibility
    var reactionCount: Int = 0
    var liftCount: Int = 0
    var hasReacted: Bool = false
    var isLiftedByCurrentUser: Bool = false
    var syncStatus: DropSyncStatus = .synced

    static func == (lhs: DropItem, rhs: DropItem) -> Bool { lhs.id == rhs.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

enum DropSyncStatus: Equatable {
    case synced
    case pending
    case failed(message: String)
}

struct FriendLink: Identifiable, Hashable {
    let id: String
    var userA: User
    var userB: User
}
