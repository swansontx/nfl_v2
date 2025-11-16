import SwiftUI

struct FriendsScreen: View {
    var body: some View {
        VStack(spacing: 16) {
            Text("Friends")
                .font(.largeTitle).bold()
            Text("Add friends by username or QR (coming soon).")
                .foregroundStyle(.secondary)
            Spacer()
        }
        .padding()
    }
}
