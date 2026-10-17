import SwiftUI

struct ContentView: View {
    var body: some View {
        ZStack {
            Color(red: 26.0 / 255.0, green: 8.0 / 255.0, blue: 72.0 / 255.0)
                .ignoresSafeArea()
            VStack(spacing: 20) {
                Image("Logo")
                    .resizable()
                    .scaledToFit()
                    .frame(maxWidth: 280)
                    .accessibilityLabel("Side Hustle Jobs PH")
                Text("SIDE HUSTLE JOBS PH")
                    .font(.title2.bold())
                    .foregroundStyle(Color(red: 245.0 / 255.0, green: 197.0 / 255.0, blue: 66.0 / 255.0))
                    .multilineTextAlignment(.center)
                Text("Edward Belacse Career Consultancy Services")
                    .font(.subheadline)
                    .foregroundStyle(.white)
                    .multilineTextAlignment(.center)
            }
            .padding(28)
        }
    }
}
