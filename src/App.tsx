import { useEffect } from "react";
import { AuthProvider } from "./context/AuthContext";
import { AppRouter } from "./routes/AppRouter";
import { api } from "./lib/api";

export default function App() {
  useEffect(() => {
    const timer = window.setTimeout(() => {
      api.warmCoreData();
    }, 300);

    return () => window.clearTimeout(timer);
  }, []);

  return (
    <AuthProvider>
      <AppRouter />
    </AuthProvider>
  );
}
