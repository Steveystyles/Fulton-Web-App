import { useEffect } from "react";
import { AppUpdateReloader } from "./components/AppUpdateReloader";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { AppRouter } from "./routes/AppRouter";
import { api } from "./lib/api";

function CoreDataWarmup() {
  const { user } = useAuth();
  const userId = user?.id;

  useEffect(() => {
    if (userId === undefined) {
      return;
    }

    const timer = window.setTimeout(() => {
      api.warmCoreData();
    }, 300);

    return () => window.clearTimeout(timer);
  }, [userId]);

  return null;
}

export default function App() {
  return (
    <>
      <AppUpdateReloader />
      <AuthProvider>
        <CoreDataWarmup />
        <AppRouter />
      </AuthProvider>
    </>
  );
}
