import SwiftUI

struct DropDetailScreen: View, Identifiable {
    @EnvironmentObject var store: DropStore
    let id = UUID()
    let drop: DropItem

    private var liveDrop: DropItem {
        store.drops.first(where: { $0.id == drop.id }) ?? drop
    }

    var body: some View {
        let currentDrop = liveDrop
        let isUpdating = store.isUpdating(dropId: currentDrop.id)
        let actionsDisabled = isUpdating || store.currentUser == nil

        VStack(spacing: 12) {
            Capsule().fill(.secondary.opacity(0.3)).frame(width: 40, height: 5).padding(.top, 8)

            Text(currentDrop.text)
                .font(.title3).bold()
                .multilineTextAlignment(.center)
                .padding(.horizontal)

            Text("\(currentDrop.author.name) • \(currentDrop.visibility.rawValue) • \(currentDrop.createdAt.formatted(date: .abbreviated, time: .shortened))")
                .font(.footnote)
                .foregroundStyle(.secondary)

            HStack(spacing: 16) {
                Button {
                    Task { await store.react(to: currentDrop) }
                } label: {
                    Label {
                        Text("\(currentDrop.reactionCount)")
                    } icon: {
                        Image(systemName: currentDrop.hasReacted ? "heart.fill" : "heart")
                    }
                }
                .tint(currentDrop.hasReacted ? .pink : .primary)
                .disabled(actionsDisabled)

                Button {
                    Task { await store.toggleLift(currentDrop) }
                } label: {
                    Label {
                        Text("\(currentDrop.liftCount)")
                    } icon: {
                        Image(systemName: "arrow.up.heart")
                    }
                }
                .tint(currentDrop.isLiftedByCurrentUser ? .blue : .primary)
                .disabled(actionsDisabled)

                Button {
                    // placeholder for replies
                } label: {
                    Label("Reply", systemImage: "text.bubble")
                }
            }
            .buttonStyle(.bordered)
            .padding(.top, 6)

            Spacer()
        }
        .frame(maxWidth: 420)
        .padding()
        .frame(maxWidth: .infinity)
        .presentationDetents([.medium, .large])
    }
}
