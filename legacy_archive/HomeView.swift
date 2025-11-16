import SwiftUI
import AuthenticationServices
import CryptoKit

struct HomeView: View {
    @EnvironmentObject var store: DropStore
    @Binding var showCreate: Bool
    @State private var nonce = ""

    var body: some View {
        VStack(spacing: 24) {
            if store.currentUser == nil {
                ProgressView("Preparing your account…")
                    .padding(.top, 60)
                Spacer()
            } else {
                Text(store.isUsingAnonymousAccount ? "Welcome to Somewhere" : "Drop something?")
                    .font(.largeTitle).bold()
                    .padding(.top, store.isUsingAnonymousAccount ? 60 : 40)

                if store.isUsingAnonymousAccount {
                    Text("Drop anonymously or sign in with Apple to save your thoughts across devices.")
                        .multilineTextAlignment(.center)
                        .foregroundStyle(.secondary)
                        .padding(.horizontal)
                } else {
                    Text("Leave a short thought where you are. Choose who can see it: Public, Friends, or Private.")
                        .multilineTextAlignment(.center)
                        .foregroundStyle(.secondary)
                        .padding(.horizontal)
                }

                Button {
                    showCreate = true
                } label: {
                    Text("Drop Something")
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(.blue.opacity(0.9))
                        .foregroundStyle(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                }
                .padding(.horizontal)

                if store.isUsingAnonymousAccount {
                    SignInWithAppleButton(.signIn, onRequest: configure, onCompletion: handle)
                        .signInWithAppleButtonStyle(.black)
                        .frame(height: 55)
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                        .padding(.horizontal)
                        .padding(.top, 4)
                } else {
                    Button("Sign out") {
                        store.signOut()
                    }
                    .padding(.top, 8)
                    .foregroundColor(.red)
                }

                Spacer()
            }
        }
        .animation(.easeInOut, value: store.currentUser?.id ?? "")
        .alert("Authentication Error", isPresented: Binding(
            get: { store.authError != nil },
            set: { if !$0 { store.authError = nil } }
        )) {
            Button("OK", role: .cancel) { store.authError = nil }
        } message: {
            Text(store.authError ?? "")
        }
    }
}

// MARK: - Sign in with Apple helpers
extension HomeView {
    private func configure(_ request: ASAuthorizationAppleIDRequest) {
        store.authError = nil
        nonce = randomNonce()
        request.requestedScopes = [.fullName, .email]
        request.nonce = sha256(nonce)
    }

    private func handle(_ result: Result<ASAuthorization, Error>) {
        switch result {
        case .success(let authResult):
            guard
                let appleID = authResult.credential as? ASAuthorizationAppleIDCredential,
                let tokenData = appleID.identityToken,
                let tokenString = String(data: tokenData, encoding: .utf8)
            else { return }

            store.signInWithApple(idToken: tokenString, nonce: nonce, fullName: appleID.fullName)

        case .failure(let error):
            print("Authorization error:", error.localizedDescription)
            store.authError = error.localizedDescription
        }
    }
}

// MARK: - Crypto helpers
private func sha256(_ input: String) -> String {
    let inputData = Data(input.utf8)
    let hashed = SHA256.hash(data: inputData)
    return hashed.map { String(format: "%02x", $0) }.joined()
}

private func randomNonce(length: Int = 32) -> String {
    let charset: [Character] = Array("0123456789ABCDEFGHIJKLMNOPQRSTUVXYZabcdefghijklmnopqrstuvwxyz-._")
    var result = ""
    var remaining = length
    while remaining > 0 {
        let randoms = (0..<16).map { _ in UInt8.random(in: 0...255) }
        for r in randoms where remaining > 0 {
            if r < charset.count { result.append(charset[Int(r % UInt8(charset.count))]); remaining -= 1 }
        }
    }
    return result
}
