import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { lazy, Suspense, useEffect, type ReactNode } from "react";
import { BottomNav } from "../components/BottomNav";
import { Header } from "../components/Header";
import { useAuth } from "../context/AuthContext";
import { api } from "../lib/api";

const Account = lazy(() => import("../pages/Account").then((module) => ({ default: module.Account })));
const Admin = lazy(() => import("../pages/Admin").then((module) => ({ default: module.Admin })));
const Leaderboard = lazy(() =>
  import("../pages/Leaderboard").then((module) => ({ default: module.Leaderboard })),
);
const Login = lazy(() => import("../pages/Login").then((module) => ({ default: module.Login })));
const LocalOps = lazy(() =>
  import("../pages/LocalOps").then((module) => ({ default: module.LocalOps })),
);
const MapGame = lazy(() =>
  import("../pages/MapGame").then((module) => ({ default: module.MapGame })),
);
const MapGamePromo = lazy(() =>
  import("../pages/MapGamePromo").then((module) => ({ default: module.MapGamePromo })),
);
const News = lazy(() => import("../pages/News").then((module) => ({ default: module.News })));
const Quiz = lazy(() => import("../pages/Quiz").then((module) => ({ default: module.Quiz })));
const Wordle = lazy(() => import("../pages/Wordle").then((module) => ({ default: module.Wordle })));

const mapTestHostnames = new Set([
  "test.fultons-quiz.com",
  "test.fultons-quiz.co.uk",
  "fultons-promo.81-102-195-20.sslip.io",
]);

function isMapTestHostname(hostname: string) {
  return mapTestHostnames.has(hostname);
}

function AppFrame({
  children,
  compact = false,
  reviewMode = false,
}: {
  children: ReactNode;
  compact?: boolean;
  reviewMode?: boolean;
}) {
  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-[430px] flex-col overflow-x-hidden bg-saints-paper shadow-2xl ring-1 ring-white/10">
      <div className="top-shell">
        <Header reviewMode={reviewMode} />
      </div>
      <div className="h-[4rem] shrink-0" aria-hidden="true" />
      <main
        id="main-content"
        className={[
          "flex-1 overflow-x-hidden px-4",
          reviewMode
            ? "pb-[max(1rem,env(safe-area-inset-bottom))]"
            : "pb-[calc(5rem+env(safe-area-inset-bottom))]",
          compact ? "pt-2" : "pt-4",
        ].join(" ")}
      >
        {children}
      </main>
      {!reviewMode ? <BottomNav /> : null}
    </div>
  );
}

function PageLoading() {
  return (
    <div className="saints-shell-bg flex min-h-dvh items-center justify-center px-4 text-white">
      <p className="text-sm font-black uppercase tracking-wider">Loading</p>
    </div>
  );
}

export function AppRouter() {
  const { acknowledgeAnnouncement, loading, pendingAnnouncements, user } = useAuth();
  const pathname =
    typeof window === "undefined" ? "/" : window.location.pathname.replace(/\/+$/, "") || "/";
  const hostname =
    typeof window === "undefined" ? "" : window.location.hostname.toLowerCase();
  const localOpsMode = pathname === "/ops";
  const promoReviewMode = pathname === "/promo";
  const mapTestMode = isMapTestHostname(hostname);
  const mapPromo = pendingAnnouncements.find(
    (announcement) => announcement.kind === "daily-map-promo",
  );

  useEffect(() => {
    if (user !== null) {
      api.warmNews();
    }
  }, [user]);

  if (localOpsMode) {
    return (
      <Suspense fallback={<PageLoading />}>
        <LocalOps />
      </Suspense>
    );
  }

  if (promoReviewMode) {
    return (
      <Suspense fallback={<PageLoading />}>
      <MapGamePromo
        reviewMode
        playHref={mapTestMode ? "/map" : "https://fultons-quiz.co.uk/map"}
      />
      </Suspense>
    );
  }

  if (mapTestMode) {
    return (
      <Suspense fallback={<PageLoading />}>
      <BrowserRouter>
        <div className="saints-shell-bg min-h-dvh overflow-x-hidden text-slate-950">
          <Routes>
            <Route
              path="/map"
              element={
                <AppFrame reviewMode>
                  <MapGame />
                </AppFrame>
              }
            />
            <Route path="*" element={<Navigate to="/map" replace />} />
          </Routes>
        </div>
      </BrowserRouter>
      </Suspense>
    );
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
    return (
      <Suspense fallback={<PageLoading />}>
        <Login />
      </Suspense>
    );
  }

  if (mapPromo) {
    return (
      <Suspense fallback={<PageLoading />}>
      <MapGamePromo
        onDismiss={() => acknowledgeAnnouncement(mapPromo.id, "dismissed")}
        onPlay={async () => {
          await acknowledgeAnnouncement(mapPromo.id, "played");
          window.location.assign("/map");
        }}
      />
      </Suspense>
    );
  }

  return (
    <Suspense fallback={<PageLoading />}>
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
    </Suspense>
  );
}
