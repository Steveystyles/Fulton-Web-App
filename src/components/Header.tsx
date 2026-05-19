import { LogOut, ShieldCheck, UserRound } from "lucide-react";
import { NavLink } from "react-router-dom";
import crestPlaceholder from "../assets/crest-placeholder.svg";
import { useAuth } from "../context/AuthContext";

export function Header() {
  const { logout, user } = useAuth();

  return (
    <header className="flex min-h-16 items-center gap-3 bg-saints-black px-4 text-white">
      <img
        src={crestPlaceholder}
        alt="Fulton's Quiz shield placeholder"
        className="h-11 w-10 shrink-0"
      />
      <div className="min-w-0 flex-1">
        <h1 className="truncate text-xl font-black leading-tight tracking-normal">
          Fulton's Quiz
        </h1>
        <p className="truncate text-xs font-bold uppercase tracking-normal text-white/60">
          {user?.username}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {user?.role === "admin" ? (
          <NavLink
            to="/admin"
            aria-label="Admin"
            className={({ isActive }) =>
              [
                "inline-flex h-10 w-10 items-center justify-center rounded-full border border-white/10 text-white transition focus:outline-none focus:ring-2 focus:ring-white/70",
                isActive ? "bg-saints-red" : "bg-white/[0.08] hover:bg-white/[0.14]",
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
              "inline-flex h-10 w-10 items-center justify-center rounded-full border border-white/10 text-white transition focus:outline-none focus:ring-2 focus:ring-white/70",
              isActive ? "bg-saints-red" : "bg-white/[0.08] hover:bg-white/[0.14]",
            ].join(" ")
          }
        >
          <UserRound aria-hidden="true" className="h-5 w-5" strokeWidth={2.3} />
        </NavLink>
        <button
          type="button"
          aria-label="Sign out"
          onClick={() => void logout()}
          className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-white/10 bg-white/[0.08] text-white transition hover:bg-white/[0.14] focus:outline-none focus:ring-2 focus:ring-white/70"
        >
          <LogOut aria-hidden="true" className="h-5 w-5" strokeWidth={2.3} />
        </button>
      </div>
    </header>
  );
}
