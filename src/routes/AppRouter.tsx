import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { useEffect, useState, type ReactNode } from "react";
import { BottomNav } from "../components/BottomNav";
import { Header } from "../components/Header";
import { NewsTicker } from "../components/NewsTicker";
import { useAuth } from "../context/AuthContext";
import { api, type DailyQuestionsResponse } from "../lib/api";
import { Account } from "../pages/Account";
import { Admin } from "../pages/Admin";
import { FootballQuiz } from "../pages/FootballQuiz";
import { GeneralQuiz } from "../pages/GeneralQuiz";
import { Leaderboard } from "../pages/Leaderboard";
import { Login } from "../pages/Login";
import { News } from "../pages/News";
import { Wordle } from "../pages/Wordle";

function AppFrame({ children, compact = false }: { children: ReactNode; compact?: boolean }) {
  return (
    <div className="mx-auto flex min-h-dvh w-screen max-w-[430px] flex-col overflow-x-hidden bg-saints-paper shadow-2xl">
      <div className="top-shell">
        <Header />
        <NewsTicker />
      </div>
      <div className="h-[6.5rem] shrink-0" aria-hidden="true" />
      <main
        id="main-content"
        className={[
          "flex-1 overflow-x-hidden px-4 pb-[calc(6rem+env(safe-area-inset-bottom))]",
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
  const [dailyQuestions, setDailyQuestions] = useState<DailyQuestionsResponse | null>(null);
  const [quizLoading, setQuizLoading] = useState(false);
  const [quizError, setQuizError] = useState<Error | null>(null);

  useEffect(() => {
    let active = true;

    if (user === null) {
      setDailyQuestions(null);
      setQuizError(null);
      setQuizLoading(false);
      return;
    }

    setQuizLoading(true);
    setQuizError(null);

    async function loadDailyQuestions() {
      try {
        const response = await api.dailyQuestions();
        if (active) {
          setDailyQuestions(response);
        }
      } catch (caughtError) {
        if (active) {
          setQuizError(
            caughtError instanceof Error
              ? caughtError
              : new Error("Daily quiz failed to load."),
          );
        }
      } finally {
        if (active) {
          setQuizLoading(false);
        }
      }
    }

    void loadDailyQuestions();

    return () => {
      active = false;
    };
  }, [user]);

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
        <Routes>
          <Route
            path="/"
            element={
              <AppFrame compact>
                <Wordle />
              </AppFrame>
            }
          />
          <Route
            path="/football"
            element={
              <AppFrame>
                <FootballQuiz
                  quizDate={dailyQuestions?.date}
                  questions={dailyQuestions?.football ?? []}
                  loading={quizLoading}
                  error={quizError}
                />
              </AppFrame>
            }
          />
          <Route
            path="/general"
            element={
              <AppFrame>
                <GeneralQuiz
                  quizDate={dailyQuestions?.date}
                  questions={dailyQuestions?.general ?? []}
                  loading={quizLoading}
                  error={quizError}
                />
              </AppFrame>
            }
          />
          <Route
            path="/leaderboard"
            element={
              <AppFrame>
                <Leaderboard />
              </AppFrame>
            }
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
              user.role === "admin" ? (
                <AppFrame>
                  <Admin />
                </AppFrame>
              ) : (
                <Navigate to="/" replace />
              )
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
