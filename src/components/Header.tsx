import { LogOut, ShieldCheck, UserRound } from "lucide-react";
import { NavLink } from "react-router-dom";
import crest from "../assets/crest.svg";
import { useAuth } from "../context/AuthContext";

const headerButtonClass =
  "inline-flex h-10 w-10 items-center justify-center rounded-full border border-white/15 text-white transition hover:bg-white/[0.16] active:bg-saints-red active:text-white saints-focus";

export function Header({ reviewMode = false }: { reviewMode?: boolean }) {
  const { logout, user } = useAuth();

  return (
    <header className="saints-stripe-edge flex min-h-16 items-center gap-3 bg-saints-black px-4 pb-1 text-white">
      <img
        src={crest}
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
          {user?.role === "admin" || user?.role === "mod" ? (
            <NavLink
              to="/admin"
              aria-label={user.role === "admin" ? "Admin" : "Players"}
              className={({ isActive }) =>
                [
                  headerButtonClass,
                  isActive
                    ? "bg-saints-red shadow-lg shadow-red-950/30"
                    : "bg-white/[0.08]",
                ].join(" ")
              }
            >
              <ShieldCheck aria-hidden="true" className="h-5 w-5" strokeWidth={2.3} />
            </NavLink>
          ) : null}
          <NavLink
            to="/account"
            aria-label="Account"
            className={({ isActive }) =>
              [
                headerButtonClass,
                isActive ? "bg-saints-red shadow-lg shadow-red-950/30" : "bg-white/[0.08]",
              ].join(" ")
            }
          >
            <UserRound aria-hidden="true" className="h-5 w-5" strokeWidth={2.3} />
          </NavLink>
          <button
            type="button"
            aria-label="Sign out"
            onClick={() => void logout()}
            className={`${headerButtonClass} bg-white/[0.08]`}
          >
            <LogOut aria-hidden="true" className="h-5 w-5" strokeWidth={2.3} />
          </button>
        </div>
      ) : null}
    </header>
  );
}
