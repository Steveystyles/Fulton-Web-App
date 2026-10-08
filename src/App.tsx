import { AppUpdateReloader } from "./components/AppUpdateReloader";
import { AppRecoveryBoundary } from "./components/AppRecoveryBoundary";
import { AuthProvider } from "./context/AuthContext";
import { AppRouter } from "./routes/AppRouter";

export default function App() {
  return (
    <AppRecoveryBoundary>
      <AppUpdateReloader />
      <AuthProvider>
        <AppRouter />
      </AuthProvider>
    </AppRecoveryBoundary>
  );
}
