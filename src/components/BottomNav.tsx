import { CircleHelp, Hash, MapPin, Newspaper, Trophy, UsersRound } from "lucide-react";
import { NavItem } from "./NavItem";

const navItems = [
  { to: "/scores", label: "Scores", icon: Trophy, end: true },
  { to: "/wordle", label: "Wordle", icon: Hash },
  { to: "/football", label: "Football", icon: CircleHelp },
  { to: "/general", label: "General", icon: UsersRound },
  { to: "/news", label: "News", icon: Newspaper },
  { to: "/facts", label: "Facts", icon: MapPin },
];

export function BottomNav() {
  return (
    <nav
      aria-label="Bottom navigation"
      className="bottom-nav border-t border-slate-200 bg-white/[0.96] px-1.5 pb-[calc(0.5rem+env(safe-area-inset-bottom))] pt-2 shadow-nav backdrop-blur"
    >
      <div className="mx-auto flex w-full max-w-[430px] gap-0.5">
        {navItems.map((item) => (
          <NavItem key={item.to} {...item} />
        ))}
      </div>
    </nav>
  );
}
