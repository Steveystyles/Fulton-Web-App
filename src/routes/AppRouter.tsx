import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { BottomNav } from "../components/BottomNav";
import { Header } from "../components/Header";
import { NewsTicker } from "../components/NewsTicker";
import { useAuth } from "../context/AuthContext";
import { Account } from "../pages/Account";
import { Admin } from "../pages/Admin";
import { FootballQuiz } from "../pages/FootballQuiz";
import { GeneralQuiz } from "../pages/GeneralQuiz";
import { Leaderboard } from "../pages/Leaderboard";
import { Login } from "../pages/Login";
import { News } from "../pages/News";
import { Wordle } from "../pages/Wordle";

export function AppRouter() {
  const { loading, user } = useAuth();

  if (loading) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-saints-black px-4 text-white">
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
      <div className="min-h-dvh overflow-x-hidden bg-slate-950 text-slate-950 sm:bg-[linear-gradient(90deg,#0b0b10_0%,#17181f_50%,#0b0b10_100%)]">
        <div className="mx-auto flex min-h-dvh w-screen max-w-[430px] flex-col overflow-x-hidden bg-saints-paper shadow-2xl">
          <div className="top-shell">
            <Header />
            <NewsTicker />
          </div>
          <div className="h-[6.5rem] shrink-0" aria-hidden="true" />
          <main
            id="main-content"
            className="flex-1 overflow-x-hidden px-4 pb-[calc(6rem+env(safe-area-inset-bottom))] pt-4"
          >
            <Routes>
              <Route path="/" element={<Wordle />} />
              <Route path="/football" element={<FootballQuiz />} />
              <Route path="/general" element={<GeneralQuiz />} />
              <Route path="/leaderboard" element={<Leaderboard />} />
              <Route path="/news" element={<News />} />
              <Route path="/account" element={<Account />} />
              <Route
                path="/admin"
                element={user.role === "admin" ? <Admin /> : <Navigate to="/" replace />}
              />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </main>
          <BottomNav />
        </div>
      </div>
    </BrowserRouter>
  );
}
