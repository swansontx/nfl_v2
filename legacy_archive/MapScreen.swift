import SwiftUI
import MapKit

struct MapScreen: View {
    @EnvironmentObject var store: DropStore
    @State private var region = MKCoordinateRegion(
        center: CLLocationCoordinate2D(latitude: 37.775, longitude: -122.418),
        span: MKCoordinateSpan(latitudeDelta: 0.02, longitudeDelta: 0.02)
    )
    @State private var selectedDrop: DropItem?
    @Binding var lastTappedLocation: CLLocationCoordinate2D

    var onRequestCreateAt: (CLLocationCoordinate2D) -> Void

    var body: some View {
        ZStack {
            Map(coordinateRegion: $region, annotationItems: store.drops) { drop in
                MapAnnotation(coordinate: drop.coordinate) {
                    Button {
                        selectedDrop = drop
                    } label: {
                        Circle()
                            .fill(color(for: drop.visibility).opacity(0.9))
                            .frame(width: 16, height: 16)
                            .shadow(radius: 2)
                    }
                }
            }
            .ignoresSafeArea(edges: .bottom)

            VStack {
                Spacer()
                HStack {
                    Spacer()
                    Button {
                        onRequestCreateAt(region.center)
                    } label: {
                        Image(systemName: "plus")
                            .font(.title2.bold())
                            .padding()
                            .background(.ultraThinMaterial)
                            .clipShape(Circle())
                            .shadow(radius: 3)
                    }
                    .padding()
                }
            }
        }
        .sheet(item: $selectedDrop) { drop in
            DropDetailScreen(drop: drop)
        }
        .onAppear {
            store.listenNearby(in: region)
        }
        .onDisappear {
            store.stopListeningNearby()
        }
        .onChange(of: region) { newRegion in
            store.listenNearby(in: newRegion)
        }
        .gesture(
            LongPressGesture(minimumDuration: 0.5)
                .sequenced(before: DragGesture(minimumDistance: 0))
                .onEnded { _ in
                    onRequestCreateAt(region.center)
                }
        )
    }

    private func color(for vis: DropVisibility) -> Color {
        switch vis {
        case .public: return .blue
        case .friends: return .green
        case .private: return .purple
        }
    }
}
