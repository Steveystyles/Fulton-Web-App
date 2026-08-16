import { AppUpdateReloader } from "./components/AppUpdateReloader";
import { AuthProvider } from "./context/AuthContext";
import { AppRouter } from "./routes/AppRouter";

export default function App() {
  return (
    <>
      <AppUpdateReloader />
      <AuthProvider>
        <AppRouter />
      </AuthProvider>
    </>
  );
}
