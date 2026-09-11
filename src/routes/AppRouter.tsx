import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { lazy, Suspense, useEffect, useRef, type ReactNode, type CSSProperties } from "react";
import { BottomNav } from "../components/BottomNav";
import { Header } from "../components/Header";
import { useAuth } from "../context/AuthContext";
import { api } from "../lib/api";

const Account = lazy(() => import("../pages/Account").then((module) => ({ default: module.Account })));
const Today = lazy(() => import("../pages/Today").then((module) => ({ default: module.Today })));
const Practice = lazy(() => import("../pages/Practice").then((module) => ({ default: module.Practice })));
const League = lazy(() => import("../pages/League").then((module) => ({ default: module.League })));
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
  const { pathname } = useLocation();
  const frameRef = useRef<HTMLDivElement>(null);
  const headerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const frame = frameRef.current;
    const header = headerRef.current;
    if (!frame || !header) return;
    const nav = frame.querySelector<HTMLElement>(".bottom-nav");
    const measure = () => {
      frame.style.setProperty("--app-header-height", `${header.getBoundingClientRect().height}px`);
      frame.style.setProperty("--app-nav-height", `${nav?.getBoundingClientRect().height ?? 0}px`);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(header);
    if (nav) observer.observe(nav);
    measure();
    return () => observer.disconnect();
  }, [reviewMode]);
  const wide = ["/", "/today", "/map", "/scores"].includes(pathname);
  return (
    <div ref={frameRef} style={{ "--shell-width": wide ? "960px" : "430px" } as CSSProperties} className={`app-frame mx-auto flex min-h-dvh w-full ${wide ? "max-w-[960px]" : "max-w-[430px]"} flex-col bg-saints-paper shadow-2xl ring-1 ring-white/10`}>
      <div ref={headerRef} className="top-shell">
        <Header reviewMode={reviewMode} />
      </div>
      <div className="app-header-space shrink-0" aria-hidden="true" />
      <main
        id="main-content"
        data-review={reviewMode}
        className={[
          "app-main flex-1 px-3 sm:px-4",
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
  const { loading, user } = useAuth();
  const pathname =
    typeof window === "undefined" ? "/" : window.location.pathname.replace(/\/+$/, "") || "/";
  const hostname =
    typeof window === "undefined" ? "" : window.location.hostname.toLowerCase();
  const localOpsMode = pathname === "/ops";
  const promoReviewMode = pathname === "/promo";
  const mapTestMode = isMapTestHostname(hostname);

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


  return (
    <Suspense fallback={<PageLoading />}>
    <BrowserRouter>
      <div className="saints-shell-bg min-h-dvh overflow-x-hidden text-slate-950">
        <Routes>
          <Route
            path="/"
            element={<AppFrame><Today /></AppFrame>}
          />
          <Route path="/today" element={<Navigate to="/" replace />} />
          <Route path="/practice" element={<AppFrame><Practice /></AppFrame>} />
          <Route path="/scores" element={<AppFrame><League /></AppFrame>} />
          <Route
            path="/scores/history"
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
          <Route path="/football" element={<Navigate to="/quiz?category=football" replace />} />
          <Route path="/general" element={<Navigate to="/quiz?category=general" replace />} />
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
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </BrowserRouter>
    </Suspense>
  );
}
