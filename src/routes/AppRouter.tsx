import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { useEffect, type ReactNode } from "react";
import { BottomNav } from "../components/BottomNav";
import { Header } from "../components/Header";
import { useAuth } from "../context/AuthContext";
import { api } from "../lib/api";
import { Account } from "../pages/Account";
import { Admin } from "../pages/Admin";
import { Leaderboard } from "../pages/Leaderboard";
import { Login } from "../pages/Login";
import { LocalOps } from "../pages/LocalOps";
import { MapGame } from "../pages/MapGame";
import { News } from "../pages/News";
import { Quiz } from "../pages/Quiz";
import { Wordle } from "../pages/Wordle";

function AppFrame({
  children,
  compact = false,
}: {
  children: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-[430px] flex-col overflow-x-hidden bg-saints-paper shadow-2xl ring-1 ring-white/10">
      <div className="top-shell">
        <Header />
      </div>
      <div className="h-[4rem] shrink-0" aria-hidden="true" />
      <main
        id="main-content"
        className={[
          "flex-1 overflow-x-hidden px-4 pb-[calc(5rem+env(safe-area-inset-bottom))]",
          compact ? "pt-2" : "pt-4",
        ].join(" ")}
      >
        {children}
      </main>
      <BottomNav />
    </div>
  );
}

export function AppRouter() {
  const { loading, user } = useAuth();
  const pathname =
    typeof window === "undefined" ? "/" : window.location.pathname.replace(/\/+$/, "") || "/";
  const localOpsMode = pathname === "/ops";

  useEffect(() => {
    if (user !== null) {
      api.warmNews();
    }
  }, [user]);

  if (localOpsMode) {
    return <LocalOps />;
  }

  if (loading) {
    return (
      <div className="saints-shell-bg flex min-h-dvh items-center justify-center px-4 text-white">
        <div className="text-center">
          <p className="text-2xl font-black">Fulton's Quiz</p>
          <p className="mt-2 text-sm font-bold uppercase tracking-normal text-white/70">
            Loading
          </p>
        </div>
      </div>
    );
  }

  if (user === null) {
    return <Login />;
  }

  return (
    <BrowserRouter>
      <div className="saints-shell-bg min-h-dvh overflow-x-hidden text-slate-950">
        <Routes>
          <Route
            path="/"
            element={<Navigate to="/scores" replace />}
          />
          <Route
            path="/scores"
            element={
              <AppFrame compact>
                <Leaderboard />
              </AppFrame>
            }
          />
          <Route
            path="/wordle"
            element={
              <AppFrame compact>
                <Wordle />
              </AppFrame>
            }
          />
          <Route
            path="/quiz"
            element={
              <AppFrame compact>
                <Quiz />
              </AppFrame>
            }
          />
          <Route path="/football" element={<Navigate to="/quiz" replace />} />
          <Route path="/general" element={<Navigate to="/quiz" replace />} />
          <Route
            path="/leaderboard"
            element={<Navigate to="/scores" replace />}
          />
          <Route
            path="/news"
            element={
              <AppFrame>
                <News />
              </AppFrame>
            }
          />
          <Route
            path="/map"
            element={
              <AppFrame>
                <MapGame />
              </AppFrame>
            }
          />
          <Route path="/facts" element={<Navigate to="/map" replace />} />
          <Route
            path="/account"
            element={
              <AppFrame>
                <Account />
              </AppFrame>
            }
          />
          <Route
            path="/admin"
            element={
              user.role === "admin" || user.role === "mod" ? (
                <AppFrame>
                  <Admin />
                </AppFrame>
              ) : (
                <Navigate to="/" replace />
              )
            }
          />
          <Route path="*" element={<Navigate to="/scores" replace />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
