import SwiftUI

struct DropsListScreen: View {
    @EnvironmentObject var store: DropStore

    var body: some View {
        NavigationStack {
            List(store.drops) { drop in
                VStack(alignment: .leading, spacing: 6) {
                    Text(drop.text).font(.headline)
                    Text("\(drop.author.name) • \(drop.visibility.rawValue)")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)

                    if case .pending = drop.syncStatus {
                        Text("Sending…")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }

                    if case let .failed(message) = drop.syncStatus {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Couldn't send drop")
                                .font(.footnote)
                                .foregroundColor(.red)
                            Text(message)
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                                .lineLimit(2)
                            Button("Retry") {
                                store.retryCreate(drop: drop)
                            }
                            .font(.footnote.weight(.semibold))
                        }
                    }
                }
            }
            .navigationTitle("Drops")
        }
    }
}
