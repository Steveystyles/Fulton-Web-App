import { CircleHelp, Hash, Newspaper, Trophy, UsersRound } from "lucide-react";
import { NavItem } from "./NavItem";

const navItems = [
  { to: "/", label: "Wordle", icon: Hash, end: true },
  { to: "/football", label: "Football", icon: CircleHelp },
  { to: "/general", label: "General", icon: UsersRound },
  { to: "/leaderboard", label: "Leaders", icon: Trophy },
  { to: "/news", label: "News", icon: Newspaper },
];

export function BottomNav() {
  return (
    <nav
      aria-label="Bottom navigation"
      className="bottom-nav border-t border-slate-200 bg-white/[0.96] px-2 pb-[calc(0.5rem+env(safe-area-inset-bottom))] pt-2 shadow-nav backdrop-blur"
    >
      <div className="mx-auto flex w-full max-w-[430px] gap-1">
        {navItems.map((item) => (
          <NavItem key={item.to} {...item} />
        ))}
      </div>
    </nav>
  );
}
