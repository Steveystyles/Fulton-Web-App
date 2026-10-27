import { House, LogOut, ShieldCheck } from "lucide-react";
import { NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ScoresDialog } from "./ScoresDialog";
import { navigateWithFreshRelease } from "./AppUpdateReloader";
import type { ActivityId } from "../lib/api";

const headerButtonClass =
  "inline-flex h-10 w-10 items-center justify-center rounded-full border border-white/15 text-white transition hover:bg-white/16 active:bg-saints-red active:text-white saints-focus";

export function Header({ reviewMode = false }: { reviewMode?: boolean }) {
  const { logout, user } = useAuth();
  const { pathname } = useLocation();
  const currentGame = pathname.slice(1) as ActivityId;
  const inGame = ["wordle", "quiz", "map"].includes(currentGame);

  return (
    <header className="saints-stripe-edge flex min-h-16 items-center gap-3 bg-saints-black px-4 pb-1 text-white">
      <img
        src="/favicon.svg"
        alt="St Mirren Football Club crest"
        className="h-11 w-11 shrink-0 rounded-full bg-white object-contain"
      />
      <div className="min-w-0 flex-1">
        <h1 className="truncate text-xl font-black leading-tight tracking-normal">
          Fulton's Quiz
        </h1>
        <p className="truncate text-xs font-bold uppercase tracking-normal text-white/60">
          {reviewMode ? "Guest review" : user?.username}
        </p>
      </div>
      {!reviewMode ? (
        <div className="flex shrink-0 items-center gap-1">
          {!inGame ? <NavLink
            to="/"
            onClick={event => navigateWithFreshRelease(event, "/")}
            aria-label="Go to games"
            className={({ isActive }) => [headerButtonClass, isActive ? "bg-saints-red shadow-lg shadow-red-950/30" : "bg-white/8"].join(" ")}
          ><House aria-hidden="true" className="h-5 w-5" strokeWidth={2.3} /></NavLink> : null}
          <ScoresDialog currentGame={inGame ? currentGame : undefined} />
          {user?.role === "admin" || user?.role === "mod" ? (
            <NavLink
              to="/admin"
              onClick={event => navigateWithFreshRelease(event, "/admin")}
              aria-label={user.role === "admin" ? "Admin" : "Players"}
              className={({ isActive }) =>
                [
                  headerButtonClass,
                  isActive
                    ? "bg-saints-red shadow-lg shadow-red-950/30"
                    : "bg-white/8",
                ].join(" ")
              }
            >
              <ShieldCheck aria-hidden="true" className="h-5 w-5" strokeWidth={2.3} />
            </NavLink>
          ) : null}
          <button
            type="button"
            aria-label="Sign out"
            onClick={() => void logout()}
            className={`${headerButtonClass} bg-white/8`}
          >
            <LogOut aria-hidden="true" className="h-5 w-5" strokeWidth={2.3} />
          </button>
        </div>
      ) : null}
    </header>
  );
}
