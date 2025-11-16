import SwiftUI
import CoreLocation

struct RootTabView: View {
    @EnvironmentObject var store: DropStore
    @State private var selectedTab: Tab = .home
    @State private var showCreate = false
    @State private var lastDropLocation = CLLocationCoordinate2D(latitude: 37.775, longitude: -122.418)

    enum Tab { case home, map, list, friends, settings }

    var body: some View {
        TabView(selection: $selectedTab) {
            // 🏠 Home
            HomeView(showCreate: $showCreate)
                .tabItem { Label("Home", systemImage: "house") }
                .tag(Tab.home)

            // 🗺️ Map
            MapScreen(
                lastTappedLocation: $lastDropLocation,
                onRequestCreateAt: { coord in
                    lastDropLocation = coord
                    showCreate = true
                }
            )
            .tabItem { Label("Map", systemImage: "map") }
            .tag(Tab.map)

            // 💬 Drops list
            DropsListScreen()
                .tabItem { Label("Drops", systemImage: "text.bubble") }
                .tag(Tab.list)

            // 👥 Friends
            FriendsScreen()
                .tabItem { Label("Friends", systemImage: "person.2") }
                .tag(Tab.friends)

            // ⚙️ Settings
            SettingsScreen()
                .tabItem { Label("Settings", systemImage: "gearshape") }
                .tag(Tab.settings)
        }
        .onChange(of: selectedTab) { newValue in
            if newValue != .map {
                store.stopListeningNearby()
            }
        }
        // 🧾 Sheet for creating a new drop
        .sheet(isPresented: $showCreate) {
            DropCreationScreen(
                defaultCoordinate: lastDropLocation,
                onCreated: { _ in
                    // Close the sheet and move to Map
                    showCreate = false
                    DispatchQueue.main.async {
                        selectedTab = .map
                    }
                },
                onCancel: {
                    // Close the sheet and return Home
                    showCreate = false
                    DispatchQueue.main.async {
                        selectedTab = .home
                    }
                }
            )
        }
    }
}
