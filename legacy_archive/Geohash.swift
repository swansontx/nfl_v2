import Foundation
import CoreLocation

enum Geohash {
    private static let base32 = Array("0123456789bcdefghjkmnpqrstuvwxyz")

    static func encode(latitude: Double, longitude: Double, precision: Int = 7) -> String {
        var latInterval = (-90.0, 90.0)
        var lonInterval = (-180.0, 180.0)
        var hash = ""
        var isEvenBit = true
        var bit = 0
        var ch = 0

        while hash.count < precision {
            if isEvenBit {
                let mid = (lonInterval.0 + lonInterval.1) / 2
                if longitude > mid { ch |= (1 << (4 - bit)); lonInterval.0 = mid }
                else { lonInterval.1 = mid }
            } else {
                let mid = (latInterval.0 + latInterval.1) / 2
                if latitude > mid { ch |= (1 << (4 - bit)); latInterval.0 = mid }
                else { latInterval.1 = mid }
            }
            isEvenBit.toggle()

            if bit < 4 { bit += 1 }
            else { hash.append(base32[ch]); bit = 0; ch = 0 }
        }
        return hash
    }

    static func prefixesCovering(region: (minLat: Double, maxLat: Double, minLon: Double, maxLon: Double),
                                 precision: Int = 5) -> Set<String> {
        let pts = [
            (region.minLat, region.minLon),
            (region.minLat, region.maxLon),
            (region.maxLat, region.minLon),
            (region.maxLat, region.maxLon)
        ]
        return Set(pts.map { encode(latitude: $0.0, longitude: $0.1, precision: precision) })
    }
}
