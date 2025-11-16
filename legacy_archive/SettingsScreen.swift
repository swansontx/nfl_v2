import SwiftUI

struct SettingsScreen: View {
    @EnvironmentObject var store: DropStore
    @State private var defaultVisibility: DropVisibility = .public
    @State private var notifyNearby = true

    var body: some View {
        NavigationStack {
            Form {
                Section("Defaults") {
                    Picker("Default visibility", selection: $defaultVisibility) {
                        ForEach(DropVisibility.allCases) { v in
                            Text(v.rawValue).tag(v)
                        }
                    }
                    Toggle("Notify me about nearby drops", isOn: $notifyNearby)
                }

                Section("Account") {
                    if let user = store.currentUser {
                        HStack {
                            Text("Signed in as")
                            Spacer()
                            Text(user.name)
                                .foregroundStyle(.secondary)
                        }
                    }

                    if store.isUsingAnonymousAccount {
                        Text("You're using a guest account. Sign in with Apple from the Home tab to sync your drops across devices.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    } else {
                        Button("Sign out") {
                            store.signOut()
                        }
                        .foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("Settings")
        }
    }
}
