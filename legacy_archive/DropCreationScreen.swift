import SwiftUI
import CoreLocation

struct DropCreationScreen: View {
    @EnvironmentObject var store: DropStore
    @Environment(\.dismiss) private var dismiss   // for closing the sheet

    @State private var text: String = ""
    @State private var visibility: DropVisibility = .public
    var defaultCoordinate: CLLocationCoordinate2D

    /// Called when a drop is created successfully
    var onCreated: (CLLocationCoordinate2D) -> Void
    /// Called when cancel is tapped
    var onCancel: () -> Void

    var body: some View {
        NavigationStack {
            Form {
                Section("Your drop") {
                    TextField("What's on your mind?", text: $text, axis: .vertical)
                        .lineLimit(3...6)
                }

                Section("Visibility") {
                    Picker("Who can see this?", selection: $visibility) {
                        ForEach(DropVisibility.allCases) { v in
                            Text(v.rawValue).tag(v)
                        }
                    }
                    .pickerStyle(.segmented)
                }

                Section("Location") {
                    Text("Will drop at your map center / current area.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Drop Something")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") {
                        onCancel()   // tell parent to handle tab state
                        dismiss()    // close sheet
                    }
                }

                ToolbarItem(placement: .confirmationAction) {
                    Button("Drop It") {
                        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
                        guard !trimmed.isEmpty else { return }

                        store.createDrop(text: trimmed,
                                         visibility: visibility,
                                         at: defaultCoordinate)
                        onCreated(defaultCoordinate)
                        dismiss()
                    }
                    .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
    }
}
